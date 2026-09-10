from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.config import ConfigError, parse_config
from agentize.hosts import cursor, opencode

CONFIG = """\
version: 1
source: .agents
hosts:
  cursor: {}
  opencode: {}
profiles:
  human:
    default: true
    mcp: [postgres, github]
  agent:
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


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")
    return tmp_path


def cursor_servers(project: Path) -> dict:
    data = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    return data["mcpServers"]


def opencode_servers(project: Path) -> dict:
    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    return data["mcp"]


# --- secrets never reach a committed file ---


def test_a_literal_secret_is_rejected():
    server = {"url": "https://e.test", "headers": {"Authorization": "abc123"}}
    raw = {"version": 1, "mcp": {"servers": {"x": server}}}
    with pytest.raises(ConfigError, match="looks like a secret but holds a literal value"):
        parse_config(raw)


def test_a_reference_is_accepted():
    raw = {
        "version": 1,
        "mcp": {
            "servers": {"x": {"url": "https://e.test", "headers": {"X-Token": "${env:TOKEN}"}}}
        },
    }
    assert parse_config(raw).servers["x"].headers["X-Token"] == "${env:TOKEN}"


def test_ordinary_literals_are_left_alone():
    raw = {
        "version": 1,
        "mcp": {"servers": {"x": {"command": ["srv"], "env": {"LOG_LEVEL": "debug"}}}},
    }
    assert parse_config(raw).servers["x"].env["LOG_LEVEL"] == "debug"


def test_literal_secret_in_env_is_rejected():
    raw = {
        "version": 1,
        "mcp": {"servers": {"x": {"command": ["srv"], "env": {"API_TOKEN": "sk-live-1"}}}},
    }
    with pytest.raises(ConfigError, match=r"mcp\.servers\.x\.env\.API_TOKEN looks like a secret"):
        parse_config(raw)


# --- Cursor ---


def test_cursor_renders_stdio_and_remote(project: Path):
    main(["-C", str(project), "mount"])
    servers = cursor_servers(project)

    assert servers["postgres"] == {
        "type": "stdio",
        "command": "postgres-mcp",
        "args": ["--readonly"],
        "env": {"DATABASE_URL": "${env:DATABASE_URL}"},
    }
    assert servers["github"] == {
        "url": "https://api.example.com/mcp",
        "headers": {"Authorization": "Bearer ${env:GITHUB_TOKEN}"},
    }


def test_cursor_reference_survives_verbatim(project: Path):
    main(["-C", str(project), "mount"])
    raw = (project / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "${env:DATABASE_URL}" in raw


def test_agent_profile_gets_fewer_servers(project: Path):
    main(["-C", str(project), "mount", "--profile", "agent"])
    assert sorted(cursor_servers(project)) == ["postgres"]


def test_switching_profile_removes_the_extra_server(project: Path):
    main(["-C", str(project), "mount"])
    assert "github" in cursor_servers(project)

    main(["-C", str(project), "mount", "--profile", "agent"])

    assert "github" not in cursor_servers(project)


def test_unrelated_cursor_mcp_keys_are_preserved(project: Path):
    write(project / ".cursor" / "mcp.json", json.dumps({"note": "keep", "mcpServers": {}}))

    main(["-C", str(project), "mount"])

    data = json.loads((project / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert data["note"] == "keep"


def test_a_single_word_command_emits_no_args():
    server = parse_config(
        {"version": 1, "mcp": {"servers": {"x": {"command": ["srv"]}}}}
    ).servers["x"]
    assert "args" not in cursor.mcp_entry(server)


# --- OpenCode ---


def test_opencode_renders_local_and_remote(project: Path):
    main(["-C", str(project), "mount"])
    servers = opencode_servers(project)

    assert servers["postgres"] == {
        "type": "local",
        "command": ["postgres-mcp", "--readonly"],
        "enabled": True,
    }
    assert "environment" not in servers["postgres"]
    assert servers["github"]["type"] == "remote"
    assert servers["github"]["url"] == "https://api.example.com/mcp"


def test_opencode_keeps_instructions_alongside_mcp(project: Path):
    main(["-C", str(project), "mount"])
    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert data["instructions"] == [".agents/shared/style.mdc"]
    assert sorted(data["mcp"]) == ["github", "postgres"]


def test_both_hosts_receive_the_same_server_set(project: Path):
    main(["-C", str(project), "mount", "--profile", "agent"])
    assert sorted(cursor_servers(project)) == sorted(opencode_servers(project))


def test_profile_order_is_preserved(project: Path):
    main(["-C", str(project), "mount"])
    assert list(opencode_servers(project)) == ["postgres", "github"]


def test_mcp_render_is_idempotent(project: Path):
    main(["-C", str(project), "mount"])
    target = project / ".cursor" / "mcp.json"
    before = target.stat().st_mtime_ns

    main(["-C", str(project), "mount"])

    assert target.stat().st_mtime_ns == before


def test_check_reports_a_missing_mcp_file(project: Path, capsys):
    assert main(["-C", str(project), "mount", "--check"]) == 1
    assert "create .cursor/mcp.json" in capsys.readouterr().out


def test_empty_profile_renders_an_empty_server_map():
    raw = {"version": 1, "profiles": {"p": {}}, "mcp": {"servers": {}}}
    config = parse_config(raw)
    rendered = json.loads(cursor.render_mcp({}, config.servers_for(config.profiles["p"])))
    assert rendered == {"mcpServers": {}}


def test_omo_alias_becomes_the_npm_name():
    assert opencode.plugin_specs(["omo", "oh-my-openagent", "other"]) == [
        "oh-my-openagent",
        "other",
    ]


def test_oes_alias_becomes_the_npm_name():
    assert opencode.plugin_specs(["oes", "opencode-extended-sidebar"]) == [
        "opencode-extended-sidebar",
    ]
    assert opencode.tui_plugin_specs(["oes", "omo"]) == ["opencode-extended-sidebar"]
    assert opencode.server_plugin_specs(["oes", "omo"]) == ["oh-my-openagent"]


def test_mount_writes_the_plugin_list(tmp_path: Path):
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  opencode:\n"
        "    plugins: [omo]\n"
        "profiles:\n"
        "  human:\n"
        "    default: true\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(tmp_path), "mount"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["plugin"] == ["oh-my-openagent"]
    assert not (tmp_path / "tui.json").exists()


def test_mount_writes_the_sidebar_to_tui_json(tmp_path: Path):
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  opencode: {}\n"
        "profiles:\n"
        "  human:\n"
        "    default: true\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(tmp_path), "mount"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["plugin"] == []
    tui = json.loads((tmp_path / "tui.json").read_text(encoding="utf-8"))
    assert tui["plugin"] == ["opencode-extended-sidebar"]
    assert tui["$schema"] == "https://opencode.ai/tui.json"


def test_mount_preserves_unrelated_tui_keys(tmp_path: Path):
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  opencode:\n"
        "    plugins: [oes]\n"
        "profiles:\n"
        "  human:\n"
        "    default: true\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")
    write(tmp_path / "tui.json", json.dumps({"theme": "system", "plugin": []}))

    assert main(["-C", str(tmp_path), "mount"]) == 0
    tui = json.loads((tmp_path / "tui.json").read_text(encoding="utf-8"))
    assert tui["theme"] == "system"
    assert tui["plugin"] == ["opencode-extended-sidebar"]


def test_opencode_entry_for_a_server_without_env():
    server = parse_config(
        {"version": 1, "mcp": {"servers": {"x": {"command": ["srv"]}}}}
    ).servers["x"]
    assert "environment" not in opencode.mcp_entry(server)


def test_opencode_keeps_literal_env_and_drops_refs():
    server = parse_config(
        {
            "version": 1,
            "mcp": {
                "servers": {
                    "x": {
                        "command": ["srv"],
                        "env": {
                            "LOG_LEVEL": "debug",
                            "DATABASE_URL": "${env:DATABASE_URL}",
                        },
                    }
                }
            },
        }
    ).servers["x"]
    entry = opencode.mcp_entry(server)
    assert entry["environment"] == {"LOG_LEVEL": "debug"}
