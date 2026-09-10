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


def test_hermes_renders_stdio_and_remote(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: home / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0

    target = home / ".hermes" / "profiles" / f"{PREFIX}human" / "config.yaml"
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


def test_agent_profile_writes_into_project_data(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: tmp_path / "unused")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount", "--profile", "agent"]) == 0

    target = project / ".agentize" / "hosts" / "hermes" / "data" / "agent" / "config.yaml"
    assert sorted(servers(target.read_text(encoding="utf-8"))) == [f"{PREFIX}postgres"]
    assert not (tmp_path / "unused").exists()


def test_unrelated_hermes_servers_are_preserved(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: home / ".hermes")
    project = tmp_path / "proj"
    write(project / "agentize.yaml", CONFIG)
    write(project / ".agents" / "shared" / "style.mdc", "style\n")
    dest = home / ".hermes" / "profiles" / f"{PREFIX}human"
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
    home = tmp_path / "home"
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: home / ".hermes")
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
    dest = home / ".hermes" / "profiles" / f"{PREFIX}human" / "config.yaml"
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
    home = tmp_path / "home"
    monkeypatch.setattr(hermes, "user_hermes_root", lambda: home / ".hermes")
    project = tmp_path / "proj"
    write(
        project / "agentize.yaml",
        "version: 1\nsource: .agents\nhosts:\n  hermes: { enabled: false }\n"
        "profiles:\n  human:\n    default: true\n    mcp: [postgres]\n"
        "mcp:\n  servers:\n    postgres:\n      command: [srv]\n",
    )
    write(project / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(project), "mount"]) == 0
    assert not (home / ".hermes").exists()


def test_a_single_word_command_emits_no_args():
    server = parse_config(
        {"version": 1, "mcp": {"servers": {"x": {"command": ["srv"]}}}}
    ).servers["x"]
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
