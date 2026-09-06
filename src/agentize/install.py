"""Install a host into `.agentize/hosts/<name>/`, never from PATH.

`run` looks here first. `--global` is the only way onto PATH. A missing copy is
an error, not a fallback. OpenCode and Cursor Agent both update themselves;
`latest` (or a missing pin) is one rolling tree they may overwrite.
"""

from __future__ import annotations

import io
import re
import shutil
import tarfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .config import Host
from .errors import AgentizeError
from .layout import (
    ensure_data_dir,
    host_version_dir,
    read_current_pin,
    write_current_pin,
)
from .platform import host_arch, host_os

GetBytes = Callable[[str], bytes]

BINARY_NAMES = {
    "opencode": ("opencode.exe", "opencode"),
    "cursor": ("cursor-agent.exe", "cursor-agent", "agent.exe", "agent"),
}

PATH_NAMES = {"opencode": "opencode", "cursor": "agent"}

OPENCODE_TAG = "https://github.com/sst/opencode/releases/download/{tag}/{asset}"
OPENCODE_LATEST = (
    "https://github.com/sst/opencode/releases/latest/download/{asset}"
)
CURSOR_ARCHIVE = "https://downloads.cursor.com/lab/{pin}/{os}/{arch}/agent-cli-package.tar.gz"
CURSOR_INSTALL = "https://cursor.com/install"
CURSOR_LAB_PIN = re.compile(r"downloads\.cursor\.com/lab/([^/\s\"']+)/")

LATEST = "latest"
FLOATING_HOSTS = frozenset({"opencode", "cursor"})


def path_name(host: str) -> str:
    """What `--global` looks up on PATH. Cursor means the agent CLI, not the IDE."""
    return PATH_NAMES.get(host, host)


def tracks_latest(host: Host) -> bool:
    """OpenCode and Cursor Agent update themselves. Missing pin or `latest` floats."""
    return host.name in FLOATING_HOSTS and host.pin in (None, LATEST)


def install_id(host: Host) -> str:
    if tracks_latest(host):
        return LATEST
    if not host.pin:
        raise AgentizeError(
            f"hosts.{host.name} has no pin; add one before running fetch"
        )
    return host.pin


def archive_url(host: str, pin: str, os_name: str, arch: str) -> str:
    if host == "opencode":
        stem = f"opencode-{os_name}-{arch}"
        asset = f"{stem}.zip" if os_name in {"windows", "darwin"} else f"{stem}.tar.gz"
        if pin == LATEST:
            return OPENCODE_LATEST.format(asset=asset)
        tag = pin if pin.startswith("v") else f"v{pin}"
        return OPENCODE_TAG.format(tag=tag, asset=asset)
    if host == "cursor":
        return CURSOR_ARCHIVE.format(pin=pin, os=os_name, arch=arch)
    raise AgentizeError(f"host {host!r} has no download recipe in this build")


def download(url: str) -> bytes:
    if not url.startswith("https://"):
        raise AgentizeError(f"refusing to fetch a non-https URL: {url}")
    try:
        with urlopen(url, timeout=60) as response:  # noqa: S310 — scheme checked above
            return response.read()
    except URLError as exc:
        raise AgentizeError(f"could not download {url}: {exc}") from exc


def resolve_cursor_pin(get: GetBytes = download) -> str:
    """The install script embeds today's lab build; there is no `/latest/` URL."""
    script = get(CURSOR_INSTALL)
    text = script.decode("utf-8", errors="replace") if isinstance(script, bytes) else script
    match = CURSOR_LAB_PIN.search(text)
    if match is None:
        raise AgentizeError(
            "could not read the current Cursor Agent version from cursor.com/install"
        )
    return match.group(1)


def extract_archive(payload: bytes, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO(payload)
    if zipfile.is_zipfile(buffer):
        buffer.seek(0)
        with zipfile.ZipFile(buffer) as archive:
            archive.extractall(dest)
        return
    buffer.seek(0)
    try:
        with tarfile.open(fileobj=buffer, mode="r:*") as archive:
            _extract_tar(archive, dest)
        return
    except tarfile.TarError as exc:
        raise AgentizeError(f"archive is neither a zip nor a tarball: {exc}") from exc


def _extract_tar(archive: tarfile.TarFile, dest: Path) -> None:
    try:
        archive.extractall(dest, filter="data")
    except TypeError:
        archive.extractall(dest)


def find_binary(root: Path, host: str) -> Path:
    names = BINARY_NAMES.get(host)
    if names is None:
        raise AgentizeError(f"host {host!r} has no known binary name")
    wanted = set(names)
    matches = sorted(
        path for path in root.rglob("*") if path.is_file() and path.name in wanted
    )
    if not matches:
        raise AgentizeError(
            f"extracted {host} but found none of: {', '.join(names)}"
        )
    return matches[0]


def fetch_host(
    project_root: Path,
    host: Host,
    *,
    os_name: str | None = None,
    arch: str | None = None,
    get: GetBytes = download,
) -> Path:
    pin = install_id(host)
    ensure_data_dir(project_root)
    dest = host_version_dir(project_root, host.name, pin)
    if dest.is_dir() and _looks_installed(dest, host.name):
        write_current_pin(project_root, host.name, pin)
        return find_binary(dest, host.name)

    url_pin = resolve_cursor_pin(get) if host.name == "cursor" and pin == LATEST else pin
    url = archive_url(host.name, url_pin, host_os(os_name), host_arch(arch))
    payload = get(url)

    staging = dest.with_name(f".{dest.name}.tmp")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        extract_archive(payload, staging)
        binary = find_binary(staging, host.name)
        if dest.exists():
            shutil.rmtree(dest)
        staging.rename(dest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    write_current_pin(project_root, host.name, pin)
    return dest / binary.relative_to(staging)


def _looks_installed(dest: Path, host: str) -> bool:
    try:
        find_binary(dest, host)
    except AgentizeError:
        return False
    return True


def isolated_binary(project_root: Path, host: Host) -> Path:
    """The project copy, or an error naming `agentize fetch` — never PATH.

    A floating host on `latest` lives in one rolling tree so its own updater
    can overwrite the binary. A numbered pin still has to match `current`.
    """
    if tracks_latest(host):
        pin = LATEST
    elif not host.pin:
        current = read_current_pin(project_root, host.name)
        if current is None:
            raise AgentizeError(
                f"no isolated {host.name} and hosts.{host.name}.pin is unset. "
                "Add a pin and run: agentize fetch"
            )
        pin = current
    else:
        pin = host.pin
        current = read_current_pin(project_root, host.name)
        if current is not None and current != pin:
            raise AgentizeError(
                f"hosts.{host.name}.pin is {pin!r} but the installed copy is "
                f"{current!r}. Run: agentize fetch"
            )

    dest = host_version_dir(project_root, host.name, pin)
    if not dest.is_dir():
        raise AgentizeError(
            f"no isolated {host.name} at {dest}. Run: agentize fetch"
        )
    return find_binary(dest, host.name)
