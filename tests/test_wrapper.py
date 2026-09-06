from __future__ import annotations

from pathlib import Path

from agentize.cli import build_parser, main
from agentize.wrapper import (
    CMD_NAME,
    FILES,
    NAME_LINE,
    PS1_NAME,
    SOURCE,
    UNIX_NAME,
    is_self_checkout,
    write_wrappers,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_this_repository_is_a_self_checkout():
    assert is_self_checkout(REPO_ROOT)
    assert NAME_LINE in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_a_consumer_folder_is_not_a_self_checkout(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "other"\n', encoding="utf-8")
    assert not is_self_checkout(tmp_path)
    assert not is_self_checkout(tmp_path / "missing")


def test_wrappers_call_uvx_from_github(tmp_path: Path):
    write_wrappers(tmp_path)
    unix = (tmp_path / UNIX_NAME).read_text(encoding="utf-8")
    ps1 = (tmp_path / PS1_NAME).read_text(encoding="utf-8")
    cmd = (tmp_path / CMD_NAME).read_text(encoding="utf-8")

    assert unix.startswith("#!/bin/sh")
    assert f"--from {SOURCE}" in unix
    assert "--refresh" in unix
    assert "AGENTIZE_OFFLINE" in unix
    assert f"--from {SOURCE}" in ps1
    assert "agentize.ps1" in cmd


def test_writing_wrappers_is_idempotent(tmp_path: Path):
    write_wrappers(tmp_path)
    before = (tmp_path / UNIX_NAME).stat().st_mtime_ns
    write_wrappers(tmp_path)
    assert (tmp_path / UNIX_NAME).stat().st_mtime_ns == before


def test_a_bare_host_flag_is_not_read_as_the_command():
    parsed = build_parser().parse_args(["--host", "opencode"])
    assert parsed.command is None
    assert parsed.host == "opencode"


def test_init_plants_the_launchers(tmp_path: Path):
    assert main(["-C", str(tmp_path), "init"]) == 0
    for name, text in FILES.items():
        assert (tmp_path / name).read_text(encoding="utf-8") == text
