from __future__ import annotations

from pathlib import Path

import yaml

from agentize.cli import main
from agentize.config import parse_config
from agentize.hosts import hermes
from agentize.user_mcp import PREFIX

CONFIG = """\
version: 1
source: .agents
hosts:
  hermes: {}
profiles:
  human:
    default: true
    mcp: [postgres, github]
  agent:
    isolate_data: true
    mcp: [postgres]
mcp:
  servers:
    postgres:
      command: [postgres-mcp, --readonly]
      env:
        DATABASE_URL: ${env:DATABASE_URL}
    github:
      url: https://api.example.com/mcp
      headers:
        Authorization: Bearer ${env:GITHUB_TOKEN}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def servers(text: str) -> dict:
    return hermes.servers_from(text)


def isolate_hermes_home(monkeypatch, root: Path) -> Path:
    """Keep drop_stale off the machine Desktop home during tests."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: root)
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (root,))
    return root


def test_hermes_renders_stdio_and_remote(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0

    target = home / "profiles" / f"{PREFIX}human" / "config.yaml"
    data = servers(target.read_text(encoding="utf-8"))
    assert data[f"{PREFIX}postgres"] == {
        "command": "postgres-mcp",
        "args": ["--readonly"],
        "env": {"DATABASE_URL": "${env:DATABASE_URL}"},
    }
    assert data[f"{PREFIX}github"] == {
        "url": "https://api.example.com/mcp",
        "headers": {"Authorization": "Bearer ${env:GITHUB_TOKEN}"},
    }
    raw = target.read_text(encoding="utf-8")
    assert "${env:DATABASE_URL}" in raw


def test_agent_profile_writes_into_desktop_home(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount", "--profile", "agent"]) == 0

    target = home / "profiles" / f"{PREFIX}agent" / "config.yaml"
    assert sorted(servers(target.read_text(encoding="utf-8"))) == [f"{PREFIX}postgres"]
    assert not (project / ".agentize" / "hosts" / "hermes").exists()


def test_bare_mount_plants_human_and_default_agent(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres, github]\n"
        "agents:\n"
        "  default:\n    isolate_data: true\n    mcp: [postgres]\n"
        "mcp:\n"
        "  servers:\n"
        "    postgres:\n      command: [postgres-mcp]\n"
        "    github:\n      url: https://api.example.com/mcp\n",
    )
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0

    human = home / "profiles" / f"{PREFIX}human" / "config.yaml"
    agent = home / "profiles" / f"{PREFIX}agent" / "config.yaml"
    assert sorted(servers(human.read_text(encoding="utf-8"))) == [
        f"{PREFIX}github",
        f"{PREFIX}postgres",
    ]
    assert sorted(servers(agent.read_text(encoding="utf-8"))) == [f"{PREFIX}postgres"]
    assert not (home / "profiles" / f"{PREFIX}default").exists()
    assert not (project / ".agentize" / "hosts" / "hermes").exists()


def test_unrelated_hermes_servers_are_preserved(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")
    dest = home / "profiles" / f"{PREFIX}human"
    write(
        dest / "config.yaml",
        yaml.safe_dump(
            {
                "model": "keep-me",
                "mcp_servers": {"filesystem": {"command": "npx", "args": ["-y", "fs"]}},
            }
        ),
    )

    assert main(["-C", str(project), "mount"]) == 0

    payload = yaml.safe_load((dest / "config.yaml").read_text(encoding="utf-8"))
    assert payload["model"] == "keep-me"
    assert "filesystem" in payload["mcp_servers"]
    assert f"{PREFIX}postgres" in payload["mcp_servers"]


def test_switching_profile_drops_stale_prefixed_keys(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres, github]\n"
        "  slim:\n    mcp: [postgres]\n"
        "mcp:\n"
        "  servers:\n"
        "    postgres:\n      command: [postgres-mcp]\n"
        "    github:\n      url: https://api.example.com/mcp\n",
    )
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0
    dest = home / "profiles" / f"{PREFIX}human" / "config.yaml"
    assert f"{PREFIX}github" in servers(dest.read_text(encoding="utf-8"))

    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres]\n"
        "mcp:\n"
        "  servers:\n"
        "    postgres:\n      command: [postgres-mcp]\n"
        "    github:\n      url: https://api.example.com/mcp\n",
    )
    assert main(["-C", str(project), "mount"]) == 0
    assert f"{PREFIX}github" not in servers(dest.read_text(encoding="utf-8"))


def test_disabled_host_writes_nothing(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\nsource: .agents\nhosts:\n  hermes: { enabled: false }\n"
        "profiles:\n  human:\n    default: true\n    mcp: [postgres]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [srv]\n",
    )
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0
    assert not (home / "profiles").exists()


def test_a_single_word_command_emits_no_args():
    server = parse_config({"version": 1, "mcp": {"servers": {"x": {"command": ["srv"]}}}}).servers[
        "x"
    ]
    assert "args" not in hermes.mcp_entry(server)


def test_cleanup_home_removes_prefixed_profiles(tmp_path: Path, monkeypatch):
    root = tmp_path / ".hermes"
    keep = root / "profiles" / "personal"
    drop = root / "profiles" / f"{PREFIX}human"
    keep.mkdir(parents=True)
    drop.mkdir(parents=True)
    (keep / "config.yaml").write_text("keep\n", encoding="utf-8")
    (drop / "config.yaml").write_text("drop\n", encoding="utf-8")
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: root)

    removed = hermes.strip_agentize_profiles(root=root)
    assert removed == (drop,)
    assert keep.is_dir()
    assert not drop.exists()


def test_user_hermes_root_prefers_existing_native_home(tmp_path: Path, monkeypatch):
    native = tmp_path / "AppData" / "Local" / "hermes"
    posix = tmp_path / "home" / ".hermes"
    native.mkdir(parents=True)
    posix.mkdir(parents=True)
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (native, posix))
    assert hermes.user_hermes_root() == native


def test_user_hermes_root_falls_back_to_dot_hermes(tmp_path: Path, monkeypatch):
    native = tmp_path / "AppData" / "Local" / "hermes"
    posix = tmp_path / "home" / ".hermes"
    posix.mkdir(parents=True)
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (native, posix))
    assert hermes.user_hermes_root() == posix


def test_user_hermes_root_defaults_to_native_when_none_exist(tmp_path: Path, monkeypatch):
    native = tmp_path / "AppData" / "Local" / "hermes"
    posix = tmp_path / "home" / ".hermes"
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (native, posix))
    assert hermes.user_hermes_root() == native


def test_hermes_root_candidates_windows_native_first(tmp_path: Path, monkeypatch):
    home = tmp_path / "Users" / "me"
    local = home / "AppData" / "Local"
    monkeypatch.setattr(hermes.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(hermes, "_user_home", lambda: home)
    assert hermes.hermes_root_candidates() == (local / "hermes", home / ".hermes")


def test_hermes_root_candidates_posix_is_dot_hermes(tmp_path: Path, monkeypatch):
    home = tmp_path / "home" / "me"
    monkeypatch.setattr(hermes.sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(hermes, "_user_home", lambda: home)
    assert hermes.hermes_root_candidates() == (home / ".hermes",)


def test_drop_stale_named_profiles_leaves_the_chosen_root(tmp_path: Path, monkeypatch):
    native = tmp_path / "AppData" / "Local" / "hermes"
    posix = tmp_path / "home" / ".hermes"
    keep = native / "profiles" / f"{PREFIX}human"
    stale = posix / "profiles" / f"{PREFIX}human"
    other = posix / "profiles" / "personal"
    keep.mkdir(parents=True)
    stale.mkdir(parents=True)
    other.mkdir(parents=True)
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (native, posix))
    identity = parse_config(
        {
            "version": 1,
            "profiles": {"human": {"default": True}},
        }
    ).profiles["human"]

    removed = hermes.drop_stale_named_profiles(identity, keep)
    assert removed == (stale,)
    assert keep.is_dir()
    assert other.is_dir()
    assert not stale.exists()


def test_hermes_copies_skillize_root_skills(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "skills" / "review" / "SKILL.md", "# review\n")

    assert main(["-C", str(project), "mount"]) == 0

    emitted = home / "profiles" / f"{PREFIX}human" / "skills" / "agentize.auto.generated.review"
    assert (emitted / "SKILL.md").read_text(encoding="utf-8") == "# review\n"


def test_hermes_copies_a_skill_into_the_profile_home(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")
    write(project / ".agents" / "shared" / "skills" / "review" / "checklist.md", "one\n")

    assert main(["-C", str(project), "mount"]) == 0

    emitted = home / "profiles" / f"{PREFIX}human" / "skills" / "agentize.auto.generated.review"
    assert (emitted / "SKILL.md").read_text(encoding="utf-8") == "# review\n"
    assert (emitted / "checklist.md").read_text(encoding="utf-8") == "one\n"
    assert not (project / ".cursor" / "skills").exists()
    assert not (project / ".agents" / "skills").exists()


def test_hermes_host_layer_wins_the_whole_skill(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# shared\n")
    write(project / ".agents" / "shared" / "skills" / "review" / "extra.md", "helper\n")
    write(project / ".agents" / "hosts" / "hermes" / "skills" / "review" / "SKILL.md", "# hermes\n")

    assert main(["-C", str(project), "mount"]) == 0

    emitted = home / "profiles" / f"{PREFIX}human" / "skills" / "agentize.auto.generated.review"
    assert (emitted / "SKILL.md").read_text(encoding="utf-8") == "# hermes\n"
    assert not (emitted / "extra.md").exists()


def test_hermes_profile_selection_narrows_skills(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres]\n    skills: [review]\n"
        "  agent:\n    isolate_data: true\n    mcp: [postgres]\n    skills: [review]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [postgres-mcp]\n",
    )
    write(project / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")
    write(project / ".agents" / "shared" / "skills" / "deploy" / "SKILL.md", "# deploy\n")

    assert main(["-C", str(project), "mount"]) == 0

    human = home / "profiles" / f"{PREFIX}human" / "skills"
    agent = home / "profiles" / f"{PREFIX}agent" / "skills"
    assert (human / "agentize.auto.generated.review" / "SKILL.md").is_file()
    assert not (human / "agentize.auto.generated.deploy").exists()
    assert (agent / "agentize.auto.generated.review" / "SKILL.md").is_file()
    assert not (agent / "agentize.auto.generated.deploy").exists()


def test_a_hand_written_hermes_skill_survives(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")
    mine = home / "profiles" / f"{PREFIX}human" / "skills" / "github"
    write(mine / "SKILL.md", "# bundled\n")

    assert main(["-C", str(project), "mount"]) == 0

    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "# bundled\n"
    assert (
        home
        / "profiles"
        / f"{PREFIX}human"
        / "skills"
        / "agentize.auto.generated.review"
        / "SKILL.md"
    ).is_file()


def test_removing_a_source_skill_deletes_the_prefixed_hermes_tree(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    skill = project / ".agents" / "shared" / "skills" / "review"
    write(skill / "SKILL.md", "# review\n")
    assert main(["-C", str(project), "mount"]) == 0
    emitted = home / "profiles" / f"{PREFIX}human" / "skills" / "agentize.auto.generated.review"
    assert emitted.is_dir()

    (skill / "SKILL.md").unlink()
    skill.rmdir()
    assert main(["-C", str(project), "mount"]) == 0
    assert not emitted.exists()


def test_a_hermes_profile_asking_for_an_absent_skill_fails(tmp_path: Path, monkeypatch, capsys):
    isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres]\n    skills: [review]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [postgres-mcp]\n",
    )
    write(project / ".agents" / "shared" / "skills" / "deploy" / "SKILL.md", "# deploy\n")

    assert main(["-C", str(project), "mount"]) == 1
    assert "review" in capsys.readouterr().err


def test_a_cursor_scoped_skill_does_not_fail_hermes(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  cursor:\n    emit_prefix: agentize.auto.generated.\n"
        "  hermes: {}\n"
        "profiles:\n"
        "  human:\n    default: true\n    mcp: [postgres]\n    skills: [graphify]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [postgres-mcp]\n",
    )
    write(
        project / ".agents" / "hosts" / "cursor" / "skills" / "graphify" / "SKILL.md",
        "# cursor\n",
    )

    assert main(["-C", str(project), "mount"]) == 0

    # Cursor plants the skill it owns; Hermes must not fail on it.
    assert (
        project / ".cursor" / "skills" / "agentize.auto.generated.graphify" / "SKILL.md"
    ).is_file()
    profile = home / "profiles" / f"{PREFIX}human"
    assert (profile / "config.yaml").is_file()
    assert not (profile / "skills" / "agentize.auto.generated.graphify").exists()


def test_hermes_emit_prefix_names_the_skill_directory(tmp_path: Path, monkeypatch):
    home = isolate_hermes_home(monkeypatch, tmp_path / "home" / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  hermes:\n    emit_prefix: agentize.auto.generated.hz.\n"
        "profiles:\n  human:\n    default: true\n    mcp: [postgres]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [postgres-mcp]\n",
    )
    write(project / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")

    assert main(["-C", str(project), "mount"]) == 0

    skills_root = home / "profiles" / f"{PREFIX}human" / "skills"
    assert (skills_root / "agentize.auto.generated.hz.review" / "SKILL.md").is_file()
    assert not (skills_root / "agentize.auto.generated.review").exists()


def test_strip_without_root_walks_every_existing_home(tmp_path: Path, monkeypatch):
    native = tmp_path / "AppData" / "Local" / "hermes"
    posix = tmp_path / "home" / ".hermes"
    drop_native = native / "profiles" / f"{PREFIX}human"
    drop_posix = posix / "profiles" / f"{PREFIX}human"
    keep = native / "profiles" / "personal"
    drop_native.mkdir(parents=True)
    drop_posix.mkdir(parents=True)
    keep.mkdir(parents=True)
    monkeypatch.setattr(hermes, "hermes_root_candidates", lambda: (native, posix))

    removed = hermes.strip_agentize_profiles()
    assert set(removed) == {drop_native, drop_posix}
    assert keep.is_dir()
