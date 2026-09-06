from __future__ import annotations

import hashlib
import io
import os
import platform
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from agentize.wrapper import FILES

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
LAUNCHERS = SCRIPTS / "launchers"
CHECKSUMS = SCRIPTS / "checksums.txt"
GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")


def posix_shell() -> str | None:
    if GIT_BASH.is_file():
        return str(GIT_BASH)
    found = shutil.which("bash")
    if found and "system32" not in found.lower():
        return found
    return None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_sidecar(directory: Path, asset: str) -> None:
    digest = _sha256((directory / asset).read_bytes())
    (directory / f"{asset}.sha256").write_text(
        f"{digest} *{asset}\n", encoding="utf-8", newline="\n"
    )


def fake_uv_tarball(directory: Path, asset: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / asset
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as tar:
        for name in ("uv", "uvx"):
            data = b"#!/bin/sh\n"
            info = tarfile.TarInfo(name=f"uv-pack/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    archive.write_bytes(payload.getvalue())
    _write_sidecar(directory, asset)


def fake_uv_zip(directory: Path, asset: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / asset
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr("uv-pack/uv.exe", b"fake-uv")
        zipped.writestr("uv-pack/uvx.exe", b"fake-uvx")
    archive.write_bytes(buffer.getvalue())
    _write_sidecar(directory, asset)


def test_committed_launchers_match_wrapper_and_checksums():
    recorded: dict[str, str] = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        recorded[name.lstrip("*")] = digest

    assert set(recorded) == set(FILES)
    for name, text in FILES.items():
        payload = (LAUNCHERS / name).read_bytes()
        assert payload.decode("utf-8") == text
        assert recorded[name] == _sha256(payload)


def test_posix_installer_refuses_the_wrong_os():
    bash = posix_shell()
    if bash is None:
        pytest.skip("Git bash is not installed")
    env = {**os.environ, "AGENTIZE_INSTALL_BASE": str(SCRIPTS)}
    env.pop("AGENTIZE_SKIP_OS_CHECK", None)
    if platform.system() == "Darwin":
        script = SCRIPTS / "install.sh"
        needle = "this installer is for Linux"
    else:
        script = SCRIPTS / "install-macos.sh"
        needle = "this installer is for macOS"
    result = subprocess.run(
        [bash, str(script)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert needle in result.stderr


def test_posix_installer_plants_verified_launchers(tmp_path: Path):
    bash = posix_shell()
    if bash is None:
        pytest.skip("Git bash is not installed")
    dest = tmp_path / "project"
    dest.mkdir()
    env = {
        **os.environ,
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(SCRIPTS),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [bash, str(SCRIPTS / "install.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for name, text in FILES.items():
        assert (dest / name).read_text(encoding="utf-8") == text


def test_posix_installer_rejects_a_bad_checksum(tmp_path: Path):
    bash = posix_shell()
    if bash is None:
        pytest.skip("Git bash is not installed")
    tree = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, tree, ignore=shutil.ignore_patterns("install*"))
    first = (tree / "checksums.txt").read_text(encoding="utf-8").split()[0]
    (tree / "checksums.txt").write_text(
        (tree / "checksums.txt").read_text(encoding="utf-8").replace(first, "0" * 64, 1),
        encoding="utf-8",
        newline="\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    env = {
        **os.environ,
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(tree),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [bash, str(SCRIPTS / "install.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "checksum failed" in result.stderr
    assert not (dest / "agentize").exists()


def test_powershell_installer_plants_verified_launchers(tmp_path: Path):
    dest = tmp_path / "project"
    dest.mkdir()
    env = {
        **os.environ,
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(SCRIPTS),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "install.ps1"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    for name, text in FILES.items():
        assert (dest / name).read_text(encoding="utf-8") == text


def test_powershell_installer_rejects_a_bad_checksum(tmp_path: Path):
    tree = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, tree, ignore=shutil.ignore_patterns("install*"))
    first = (tree / "checksums.txt").read_text(encoding="utf-8").split()[0]
    (tree / "checksums.txt").write_text(
        (tree / "checksums.txt").read_text(encoding="utf-8").replace(first, "0" * 64, 1),
        encoding="utf-8",
        newline="\n",
    )
    dest = tmp_path / "dest"
    dest.mkdir()
    env = {
        **os.environ,
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(tree),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "install.ps1"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    combined = result.stderr + result.stdout
    assert "checksum failed" in combined
    assert not (dest / "agentize.ps1").exists()


def test_posix_installer_downloads_uv_when_missing(tmp_path: Path):
    bash = posix_shell()
    if bash is None:
        pytest.skip("Git bash is not installed")
    release = tmp_path / "uv-release"
    asset = "uv-x86_64-unknown-linux-gnu.tar.gz"
    fake_uv_tarball(release, asset)
    dest = tmp_path / "project"
    dest.mkdir()
    uv_bin = tmp_path / "uv-bin"
    env = {
        **os.environ,
        "PATH": "/usr/bin:/bin",
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(SCRIPTS),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_RELEASE": str(release),
        "AGENTIZE_UV_ASSET": asset,
        "AGENTIZE_UV_BIN": str(uv_bin),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [bash, str(SCRIPTS / "install.sh")],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (uv_bin / "uv").is_file()
    assert (uv_bin / "uvx").is_file()
    assert "uv not found" in result.stdout
    assert (dest / "agentize").is_file()


def test_powershell_installer_downloads_uv_when_missing(tmp_path: Path):
    release = tmp_path / "uv-release"
    asset = "uv-x86_64-pc-windows-msvc.zip"
    fake_uv_zip(release, asset)
    dest = tmp_path / "project"
    dest.mkdir()
    uv_bin = tmp_path / "uv-bin"
    env = {
        **os.environ,
        "Path": r"C:\Windows\System32;C:\Windows",
        "AGENTIZE_SKIP_OS_CHECK": "1",
        "AGENTIZE_INSTALL_BASE": str(SCRIPTS),
        "AGENTIZE_DEST": str(dest),
        "AGENTIZE_UV_RELEASE": str(release),
        "AGENTIZE_UV_ASSET": asset,
        "AGENTIZE_UV_BIN": str(uv_bin),
        "AGENTIZE_UV_SKIP_PATH_WRITE": "1",
    }
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPTS / "install.ps1"),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert (uv_bin / "uv.exe").is_file()
    assert (uv_bin / "uvx.exe").is_file()
    assert "uv not found" in (result.stdout + result.stderr)
    assert (dest / "agentize.ps1").is_file()
