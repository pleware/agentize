from __future__ import annotations

from pathlib import Path

from agentize.cli import main
from agentize.session import LastRun, load_last, remember, user_last_path


def test_remember_writes_project_and_user_copy(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setenv("AGENTIZE_HOME", str(home))

    remember(project, LastRun(host="opencode", profile="agent", use_global=False))

    last = load_last(project)
    assert last.host == "opencode"
    assert last.profile == "agent"
    assert user_last_path().read_text(encoding="utf-8")


def test_an_empty_project_falls_back_to_the_user_file(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("AGENTIZE_HOME", str(home))

    other = tmp_path / "other"
    other.mkdir()
    remember(other, LastRun(host="cursor", profile="human"))

    last = load_last(empty)
    assert last.host == "cursor"
    assert last.profile == "human"


def test_bare_agentize_repeats_the_last_host(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("AGENTIZE_HOME", str(home))
    (tmp_path / "agentize.yaml").write_text(
        "version: 1\n"
        "hosts:\n  cursor: {}\n  opencode: {}\n"
        "profiles:\n  human:\n    default: true\n",
        encoding="utf-8",
    )
    remember(tmp_path, LastRun(host="opencode", profile="human", use_global=True))

    seen: list[list[str]] = []
    monkeypatch.setattr("agentize.cli.spawn", lambda root, argv, env: seen.append(argv) or 0)
    monkeypatch.setattr(
        "agentize.cli.executable", lambda root, host, use_global: f"/bin/{host.name}"
    )

    assert main(["-C", str(tmp_path), "run"]) == 0
    assert seen == [["/bin/opencode"]]


def test_empty_directory_repeats_the_user_last_host(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("AGENTIZE_HOME", str(home))

    seeded = tmp_path / "seeded"
    seeded.mkdir()
    remember(seeded, LastRun(host="opencode"))

    seen: list[list[str]] = []
    monkeypatch.setattr("agentize.cli.spawn", lambda root, argv, env: seen.append(argv) or 0)
    monkeypatch.setattr("agentize.cli.global_executable", lambda name: f"/bin/{name}")

    assert main(["-C", str(empty)]) == 0
    assert seen == [["/bin/opencode"]]
    assert (empty / ".agentize" / "last.yaml").is_file()


def test_empty_directory_without_memory_asks_for_a_host(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    empty = tmp_path / "empty"
    empty.mkdir()

    assert main(["-C", str(empty)]) == 1
    assert "no last host" in capsys.readouterr().err
