from __future__ import annotations

from pathlib import Path

from agentize.cli import main
from agentize.hosts import hermes
from agentize.session import LastRun, remember
from agentize.store_tree import data_dir, ensure_data_dir
from agentize.wrapper import FILES, PS1_NAME, write_wrappers


def test_cleanup_removes_data_and_matching_launchers(tmp_path: Path):
    assert main(["-C", str(tmp_path), "init"]) == 0
    (tmp_path / "agentize.yaml").write_text("version: 1\n", encoding="utf-8")

    assert main(["-C", str(tmp_path), "cleanup"]) == 0

    assert not data_dir(tmp_path).exists()
    for name in FILES:
        assert not (tmp_path / name).exists()
    assert (tmp_path / "agentize.yaml").read_text(encoding="utf-8") == "version: 1\n"


def test_cleanup_flag_is_the_same_as_the_command(tmp_path: Path):
    assert main(["-C", str(tmp_path), "init"]) == 0

    assert main(["-C", str(tmp_path), "--cleanup"]) == 0

    assert not data_dir(tmp_path).exists()
    for name in FILES:
        assert not (tmp_path / name).exists()


def test_cleanup_is_idempotent(tmp_path: Path, capsys):
    assert main(["-C", str(tmp_path), "cleanup"]) == 0
    assert "nothing to clean" in capsys.readouterr().out


def test_check_reports_without_deleting(tmp_path: Path):
    assert main(["-C", str(tmp_path), "init"]) == 0

    assert main(["-C", str(tmp_path), "cleanup", "--check"]) == 1

    assert data_dir(tmp_path).is_dir()
    for name in FILES:
        assert (tmp_path / name).is_file()


def test_a_hand_edited_launcher_survives(tmp_path: Path):
    write_wrappers(tmp_path)
    ensure_data_dir(tmp_path)
    (tmp_path / PS1_NAME).write_text("edited by hand\n", encoding="utf-8")

    assert main(["-C", str(tmp_path), "cleanup"]) == 0

    assert not data_dir(tmp_path).exists()
    assert (tmp_path / PS1_NAME).read_text(encoding="utf-8") == "edited by hand\n"
    for name in FILES:
        if name != PS1_NAME:
            assert not (tmp_path / name).exists()


def test_self_checkout_keeps_its_launchers(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "agentize"\n', encoding="utf-8")
    write_wrappers(tmp_path)
    ensure_data_dir(tmp_path)

    assert main(["-C", str(tmp_path), "cleanup"]) == 0

    assert not data_dir(tmp_path).exists()
    for name in FILES:
        assert (tmp_path / name).is_file()


def test_home_is_left_alone_unless_asked(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("AGENTIZE_HOME", str(home))
    remember(project, LastRun(host="opencode", profile="human"))

    assert main(["-C", str(project), "cleanup"]) == 0

    assert not data_dir(project).exists()
    assert (home / "last.yaml").is_file()


def test_home_flag_removes_the_user_tree(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("AGENTIZE_HOME", str(home))
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (tmp_path / "hermes",))
    remember(project, LastRun(host="opencode", profile="human"))

    assert main(["-C", str(project), "--cleanup", "--home"]) == 0

    assert not data_dir(project).exists()
    assert not home.exists()


def test_cleanup_does_not_unmount_host_files(tmp_path: Path):
    assert main(["-C", str(tmp_path), "init"]) == 0
    (tmp_path / "opencode.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("keep me\n", encoding="utf-8")
    cursor_rule = tmp_path / ".cursor" / "rules" / "auto.example.mdc"
    cursor_rule.parent.mkdir(parents=True)
    cursor_rule.write_text("rule\n", encoding="utf-8")

    assert main(["-C", str(tmp_path), "cleanup"]) == 0

    assert (tmp_path / "opencode.json").read_text(encoding="utf-8") == "{}\n"
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == "keep me\n"
    assert cursor_rule.read_text(encoding="utf-8") == "rule\n"


def test_the_root_gitignore_is_never_modified(tmp_path: Path):
    ignore = tmp_path / ".gitignore"
    ignore.write_text("/build\n", encoding="utf-8")
    before = ignore.read_bytes()
    assert main(["-C", str(tmp_path), "init"]) == 0

    assert main(["-C", str(tmp_path), "cleanup"]) == 0

    assert ignore.read_bytes() == before
