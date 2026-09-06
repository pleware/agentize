from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.config import parse_config
from agentize.errors import AgentizeError
from agentize.install import (
    CURSOR_INSTALL,
    LATEST,
    archive_url,
    extract_archive,
    fetch_host,
    find_binary,
    isolated_binary,
    path_name,
    resolve_cursor_pin,
    tracks_latest,
)
from agentize.launch import executable
from agentize.layout import host_version_dir, read_current_pin
from agentize.platform import host_arch, host_os


def _zip_with_binary(name: str, payload: bytes = b"#!/bin/sh\n") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"pkg/{name}", payload)
    return buffer.getvalue()


def test_cursor_on_path_means_the_agent_cli_not_the_ide():
    assert path_name("cursor") == "agent"
    assert path_name("opencode") == "opencode"


def test_archive_urls_are_https_and_pinned():
    assert archive_url("opencode", "1.18.4", "linux", "x64").startswith("https://")
    assert archive_url("opencode", "1.18.4", "linux", "x64").endswith(
        "/v1.18.4/opencode-linux-x64.tar.gz"
    )
    assert archive_url("opencode", "v1.18.4", "windows", "x64").endswith(
        "/v1.18.4/opencode-windows-x64.zip"
    )
    cursor = archive_url("cursor", "2026.09.02-c22c1a3", "linux", "x64")
    assert "2026.09.02-c22c1a3" in cursor
    assert cursor.endswith("/linux/x64/agent-cli-package.tar.gz")
    assert archive_url("cursor", "2026.09.02-c22c1a3", "windows", "x64").endswith(
        "/windows/x64/agent-cli-package.zip"
    )
    latest = archive_url("opencode", LATEST, "linux", "x64")
    assert latest.endswith("/latest/download/opencode-linux-x64.tar.gz")


def test_unknown_host_has_no_recipe():
    with pytest.raises(AgentizeError, match="no download recipe"):
        archive_url("claude", "1", "linux", "x64")


def test_platform_mapping_is_explicit():
    assert host_os("win32") == "windows"
    assert host_os("linux") == "linux"
    assert host_arch("AMD64") == "x64"
    assert host_arch("aarch64") == "arm64"
    with pytest.raises(AgentizeError, match="unsupported operating system"):
        host_os("freebsd")


def test_cursor_windows_package_uses_a_cmd_launcher(tmp_path: Path):
    dest = tmp_path / "out"
    extract_archive(_zip_with_binary("cursor-agent.cmd", b"@echo off\n"), dest)
    found = find_binary(dest, "cursor")
    assert found.name == "cursor-agent.cmd"


def test_extract_and_find_nested_binary(tmp_path: Path):
    dest = tmp_path / "out"
    extract_archive(_zip_with_binary("opencode"), dest)
    found = find_binary(dest, "opencode")
    assert found.name == "opencode"
    assert found.read_bytes().startswith(b"#!")


def test_fetch_writes_the_pin_pointer(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"opencode": {"pin": "1.2.3"}}}
    ).hosts["opencode"]
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return _zip_with_binary("opencode")

    binary = fetch_host(tmp_path, host, os_name="linux", arch="x64", get=get)

    assert seen == [archive_url("opencode", "1.2.3", "linux", "x64")]
    assert binary.is_file()
    assert read_current_pin(tmp_path, "opencode") == "1.2.3"
    assert isolated_binary(tmp_path, host) == binary


def test_a_second_fetch_does_not_download_again(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"opencode": {"pin": "1.2.3"}}}
    ).hosts["opencode"]
    hits = {"n": 0}

    def get(url: str) -> bytes:
        hits["n"] += 1
        return _zip_with_binary("opencode")

    fetch_host(tmp_path, host, os_name="linux", arch="x64", get=get)
    fetch_host(tmp_path, host, os_name="linux", arch="x64", get=get)
    assert hits["n"] == 1


def test_run_refuses_path_when_the_copy_is_missing(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"opencode": {"pin": "9.9.9"}}}
    ).hosts["opencode"]
    with pytest.raises(AgentizeError, match="agentize fetch"):
        isolated_binary(tmp_path, host)


def test_a_stale_current_pin_is_an_error(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"opencode": {"pin": "2.0.0"}}}
    ).hosts["opencode"]
    dest = host_version_dir(tmp_path, "opencode", "1.0.0")
    dest.mkdir(parents=True)
    (dest / "opencode").write_bytes(b"x")
    from agentize.layout import write_current_pin

    write_current_pin(tmp_path, "opencode", "1.0.0")
    with pytest.raises(AgentizeError, match="installed copy is '1.0.0'"):
        isolated_binary(tmp_path, host)


def test_global_flag_uses_path_lookup(monkeypatch):
    host = parse_config({"version": 1, "hosts": {"opencode": {}}}).hosts["opencode"]
    monkeypatch.setattr("agentize.launch.shutil.which", lambda name: None)
    with pytest.raises(AgentizeError, match="not on PATH"):
        executable(Path("."), host, use_global=True)


def test_cursor_without_a_pin_tracks_latest():
    host = parse_config({"version": 1, "hosts": {"cursor": {}}}).hosts["cursor"]
    assert tracks_latest(host)


def test_resolve_cursor_pin_reads_the_lab_build():
    script = (
        b'DOWNLOAD_URL="https://downloads.cursor.com/lab/2026.09.02-c22c1a3/'
        b'${OS}/${ARCH}/agent-cli-package.tar.gz"\n'
    )
    assert resolve_cursor_pin(get=lambda url: script) == "2026.09.02-c22c1a3"


def test_resolve_cursor_pin_fails_when_the_script_has_no_url():
    with pytest.raises(AgentizeError, match="cursor.com/install"):
        resolve_cursor_pin(get=lambda url: b"#!/bin/sh\necho hi\n")


def test_cursor_fetch_without_a_pin_resolves_the_install_script(tmp_path: Path):
    host = parse_config({"version": 1, "hosts": {"cursor": {}}}).hosts["cursor"]
    seen: list[str] = []
    script = (
        b'DOWNLOAD_URL="https://downloads.cursor.com/lab/2026.09.02-c22c1a3/'
        b'${OS}/${ARCH}/agent-cli-package.tar.gz"\n'
    )

    def get(url: str) -> bytes:
        seen.append(url)
        if url == CURSOR_INSTALL:
            return script
        return _zip_with_binary("cursor-agent")

    binary = fetch_host(tmp_path, host, os_name="linux", arch="x64", get=get)
    assert seen[0] == CURSOR_INSTALL
    assert seen[1] == archive_url("cursor", "2026.09.02-c22c1a3", "linux", "x64")
    assert read_current_pin(tmp_path, "cursor") == LATEST
    assert isolated_binary(tmp_path, host) == binary


def test_cursor_latest_does_not_care_that_the_binary_self_updated(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"cursor": {"pin": "latest"}}}
    ).hosts["cursor"]
    dest = host_version_dir(tmp_path, "cursor", LATEST)
    dest.mkdir(parents=True)
    (dest / "cursor-agent").write_bytes(b"self-updated")
    from agentize.layout import write_current_pin

    write_current_pin(tmp_path, "cursor", "2026.01.01-deadbee")
    assert isolated_binary(tmp_path, host).read_bytes() == b"self-updated"


def test_opencode_without_a_pin_tracks_latest():
    host = parse_config({"version": 1, "hosts": {"opencode": {}}}).hosts["opencode"]
    assert tracks_latest(host)
    assert archive_url("opencode", LATEST, "windows", "x64").endswith(
        "/latest/download/opencode-windows-x64.zip"
    )


def test_opencode_fetch_without_a_pin_installs_latest(tmp_path: Path):
    host = parse_config({"version": 1, "hosts": {"opencode": {}}}).hosts["opencode"]
    seen: list[str] = []

    def get(url: str) -> bytes:
        seen.append(url)
        return _zip_with_binary("opencode")

    binary = fetch_host(tmp_path, host, os_name="linux", arch="x64", get=get)
    assert seen == [archive_url("opencode", LATEST, "linux", "x64")]
    assert read_current_pin(tmp_path, "opencode") == LATEST
    assert isolated_binary(tmp_path, host) == binary


def test_opencode_latest_does_not_care_that_the_binary_self_updated(tmp_path: Path):
    host = parse_config(
        {"version": 1, "hosts": {"opencode": {"pin": "latest"}}}
    ).hosts["opencode"]
    dest = host_version_dir(tmp_path, "opencode", LATEST)
    dest.mkdir(parents=True)
    (dest / "opencode").write_bytes(b"self-updated")
    from agentize.layout import write_current_pin

    write_current_pin(tmp_path, "opencode", "1.99.0")
    assert isolated_binary(tmp_path, host).read_bytes() == b"self-updated"


def test_cli_fetch_installs_the_enabled_host(tmp_path: Path, monkeypatch):
    (tmp_path / "agentize.yaml").write_text(
        "version: 1\nhosts:\n  opencode:\n    pin: 1.2.3\nprofiles:\n  human:\n    default: true\n",
        encoding="utf-8",
    )

    def get(url: str) -> bytes:
        return _zip_with_binary("opencode")

    monkeypatch.setattr("agentize.cli.fetch_host", lambda root, host: fetch_host(
        root, host, os_name="linux", arch="x64", get=get
    ))

    assert main(["-C", str(tmp_path), "fetch"]) == 0
    assert read_current_pin(tmp_path, "opencode") == "1.2.3"


def test_cli_run_without_a_copy_names_fetch(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    (tmp_path / "agentize.yaml").write_text(
        "version: 1\nhosts:\n  opencode:\n    pin: 1.2.3\nprofiles:\n  human:\n    default: true\n",
        encoding="utf-8",
    )
    assert main(["-C", str(tmp_path), "run"]) == 1
    assert "agentize fetch" in capsys.readouterr().err
