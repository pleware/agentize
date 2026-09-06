from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.config import CONFIG_NAME
from agentize.store_tree import GITIGNORE, config_is_ignored, config_path, data_dir, ensure_data_dir


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "--quiet")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    return tmp_path


def test_policy_lives_at_the_project_root(tmp_path: Path):
    assert config_path(tmp_path) == tmp_path / "agentize.yaml"
    assert CONFIG_NAME == "agentize.yaml"


def test_the_data_directory_ignores_itself(tmp_path: Path):
    directory = ensure_data_dir(tmp_path)
    assert (directory / ".gitignore").read_text(encoding="utf-8") == GITIGNORE


def test_creating_the_data_directory_is_idempotent(tmp_path: Path):
    ensure_data_dir(tmp_path)
    before = (data_dir(tmp_path) / ".gitignore").stat().st_mtime_ns
    ensure_data_dir(tmp_path)
    assert (data_dir(tmp_path) / ".gitignore").stat().st_mtime_ns == before


def test_a_damaged_ignore_file_is_repaired(tmp_path: Path):
    directory = ensure_data_dir(tmp_path)
    (directory / ".gitignore").write_text("everything is fine\n", encoding="utf-8")
    ensure_data_dir(tmp_path)
    assert (directory / ".gitignore").read_text(encoding="utf-8") == GITIGNORE


def test_nothing_under_the_data_directory_is_tracked(repo: Path):
    directory = ensure_data_dir(repo)
    (directory / "opencode").mkdir()
    (directory / "opencode" / "opencode.db").write_bytes(b"\x00")
    config_path(repo).write_text("version: 1\n", encoding="utf-8")

    git(repo, "add", "-A")
    tracked = git(repo, "ls-files").split()

    assert tracked == ["agentize.yaml"]


def test_the_root_gitignore_is_never_modified(repo: Path):
    root_ignore = repo / ".gitignore"
    root_ignore.write_text("/build\n", encoding="utf-8")
    before = root_ignore.read_bytes()

    ensure_data_dir(repo)

    assert root_ignore.read_bytes() == before


def test_a_deny_by_default_repo_hides_the_policy(repo: Path):
    (repo / ".gitignore").write_text("/*\n!/.gitignore\n", encoding="utf-8")
    assert config_is_ignored(repo)


def test_whitelisting_the_policy_clears_it(repo: Path):
    (repo / ".gitignore").write_text("/*\n!/.gitignore\n!/agentize.yaml\n", encoding="utf-8")
    assert not config_is_ignored(repo)


def test_an_ordinary_repo_needs_no_rule(repo: Path):
    ensure_data_dir(repo)
    assert not config_is_ignored(repo)


def test_init_fails_loudly_when_the_policy_would_be_ignored(repo: Path, capsys):
    (repo / ".gitignore").write_text("/*\n", encoding="utf-8")

    assert main(["-C", str(repo), "init"]) == 1

    stderr = capsys.readouterr().err
    assert "agentize.yaml is ignored" in stderr
    assert "!/agentize.yaml" in stderr


def test_init_succeeds_in_a_clean_repo(repo: Path):
    assert main(["-C", str(repo), "init"]) == 0
    assert (data_dir(repo) / ".gitignore").is_file()
