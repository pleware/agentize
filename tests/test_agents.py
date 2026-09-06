from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.config import ConfigError, parse_config
from agentize.resolve import resolve
from agentize.session import load_last

AGENTS = {
    "version": 1,
    "hosts": {"opencode": {}},
    "profiles": {"human": {"default": True}},
    "agents": {
        "default": {
            "isolate_data": True,
            "git": {"user_name": "acme-agent", "user_email": "agent@example.com"},
            "mcp": ["postgres"],
            "lsp": False,
        },
        "php": {"lsp": ["phpantom"], "needs": ["php@8.3", "phpantom"]},
        "go": {"lsp": ["gopls"], "git": {"user_email": "go-agent@example.com"}},
    },
    "mcp": {"servers": {"postgres": {"command": ["postgres-mcp"]}}},
    "lsp": {
        "servers": {
            "phpantom": {
                "command": ["phpantom_lsp", "--stdio"],
                "extensions": [".php"],
            },
            "gopls": {"command": ["gopls"], "extensions": [".go"]},
            "php intelephense": {"disabled": True},
        }
    },
}


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_agents_without_default_are_rejected():
    raw = {"version": 1, "agents": {"php": {"lsp": False}}}
    with pytest.raises(ConfigError, match="agents.default is required"):
        parse_config(raw)


def test_build_and_plan_slugs_are_reserved():
    raw = {"version": 1, "agents": {"default": {}, "build": {}}}
    with pytest.raises(ConfigError, match="collides with OpenCode's built-in agent"):
        parse_config(raw)


def test_needs_must_look_like_mise_tools():
    raw = {
        "version": 1,
        "agents": {"default": {"needs": ["../php"]}},
    }
    with pytest.raises(ConfigError, match="not a mise tool name"):
        parse_config(raw)


def test_slug_overrides_needs():
    config = parse_config(
        {
            "version": 1,
            "agents": {
                "default": {"needs": ["php@8.3"]},
                "php74": {"needs": ["php@7.4"]},
            },
        }
    )
    assert config.resolve_agent("default").needs == ("php@8.3",)
    assert config.resolve_agent("php74").needs == ("php@7.4",)


def test_unknown_lsp_name_is_rejected():
    raw = {
        "version": 1,
        "agents": {"default": {"lsp": ["nope"]}},
        "lsp": {"servers": {"phpantom": {"command": ["phpantom_lsp"]}}},
    }
    with pytest.raises(ConfigError, match="unknown LSP server 'nope'"):
        parse_config(raw)


def test_enabled_lsp_server_needs_a_command():
    raw = {"version": 1, "lsp": {"servers": {"phpantom": {"extensions": [".php"]}}}}
    with pytest.raises(ConfigError, match="must set command unless disabled"):
        parse_config(raw)


def test_slug_inherits_then_overrides(tmp_path: Path):
    config = parse_config(AGENTS)
    php = config.resolve_agent("php")
    go = config.resolve_agent("go")

    assert php.isolate_data
    assert php.git is not None
    assert php.git.user_name == "acme-agent"
    assert php.git.user_email == "agent@example.com"
    assert php.mcp == ("postgres",)
    assert php.lsp.names == ("phpantom",)
    assert php.needs == ("php@8.3", "phpantom")
    assert php.origin == "agent"

    assert go.git is not None
    assert go.git.user_name == "acme-agent"
    assert go.git.user_email == "go-agent@example.com"
    assert go.lsp.names == ("gopls",)


def test_select_driver_rejects_both_flags():
    config = parse_config(AGENTS)
    with pytest.raises(ConfigError, match="not both"):
        config.select_driver("human", "php")


def test_select_driver_prefers_last_agent():
    config = parse_config(AGENTS)
    chosen = config.select_driver(None, None, last_profile="human", last_agent="php")
    assert chosen.name == "php"
    assert chosen.origin == "agent"


def test_stale_last_agent_is_ignored():
    config = parse_config({"version": 1, "profiles": {"human": {"default": True}}})
    chosen = config.select_driver(None, None, last_agent="php")
    assert chosen.name == "human"


def test_agent_layers_are_default_then_slug():
    config = parse_config(AGENTS)
    listing = [
        "shared/a.mdc",
        "agents/default/rule.mdc",
        "agents/php/rule.mdc",
        "agents/go/rule.mdc",
        "profiles/human/rule.mdc",
    ]
    php = config.resolve_agent("php")
    resolved = resolve(config, listing, host="opencode", identity=php)
    assert [item.layer for item in resolved if item.key == "rule.mdc"] == ["agents/php"]
    assert [item.key for item in resolved] == ["a.mdc", "rule.mdc"]


def test_pass_profile_and_agent_is_an_error(tmp_path: Path, capsys):
    write(tmp_path / "agentize.yaml", "version: 1\nprofiles:\n  human:\n    default: true\n")
    assert main(["-C", str(tmp_path), "mount", "--profile", "human", "--agent", "php"]) == 1
    assert "not both" in capsys.readouterr().err


def test_mount_agent_writes_only_that_lsp(tmp_path: Path):
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  opencode: {}\n"
        "profiles:\n  human:\n    default: true\n"
        "agents:\n"
        "  default:\n    lsp: false\n"
        "  php:\n    lsp: [phpantom]\n"
        "lsp:\n"
        "  servers:\n"
        "    phpantom:\n"
        "      command: [phpantom_lsp, --stdio]\n"
        "      extensions: [.php]\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(tmp_path), "mount", "--agent", "php"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["lsp"] == {
        "phpantom": {"command": ["phpantom_lsp", "--stdio"], "extensions": [".php"]}
    }
    assert data["permission"]["lsp"] == "allow"

    assert main(["-C", str(tmp_path), "mount", "--profile", "human"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["lsp"] is False
    assert data["permission"]["lsp"] == "deny"


def test_run_mounts_before_spawn(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n  opencode: {}\n"
        "profiles:\n  human:\n    default: true\n"
        "agents:\n"
        "  default:\n    isolate_data: true\n"
        "  php:\n    lsp: [phpantom]\n"
        "lsp:\n"
        "  servers:\n"
        "    phpantom:\n      command: [phpantom_lsp]\n      extensions: [.php]\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")
    monkeypatch.setattr("agentize.cli.spawn", lambda root, argv, env: 0)
    monkeypatch.setattr(
        "agentize.cli.executable", lambda root, host, use_global: f"/bin/{host.name}"
    )

    assert main(["-C", str(tmp_path), "run", "--agent", "php"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert "phpantom" in data["lsp"]
    last = load_last(tmp_path)
    assert last.agent == "php"
    assert last.profile is None


def test_old_profiles_agent_still_loads():
    config = parse_config(
        {
            "version": 1,
            "profiles": {
                "human": {"default": True},
                "agent": {"isolate_data": True, "mcp": ["postgres"]},
            },
            "mcp": {"servers": {"postgres": {"command": ["postgres-mcp"]}}},
        }
    )
    assert config.select_profile("agent").isolate_data
    assert config.agents == {}
