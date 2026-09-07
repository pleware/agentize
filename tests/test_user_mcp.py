from __future__ import annotations

import json
from pathlib import Path

import yaml

from agentize.cascade import absolutize_command
from agentize.config import parse_config
from agentize.user_mcp import (
    PREFIX,
    collect_user_mcp_servers,
    cursor_user_mcp_enabled,
    plan_user_mcp,
    prefixed_name,
    render_user_mcp,
    strip_user_mcp_prefix,
)

PARENT = """\
version: 1
source: .agents
hosts:
  cursor:
    emit_prefix: auto.
profiles:
  human:
    default: true
    mcp: [orchestrator, atlassian]
mcp:
  servers:
    orchestrator:
      command: [uv, run, --directory, family/orch, masstrade-agent]
    atlassian:
      command: [uvx, mcp-atlassian]
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_cursor_user_mcp_defaults_on():
    config = parse_config({"version": 1, "hosts": {"cursor": {}}})
    assert cursor_user_mcp_enabled(config)
    opencode = parse_config({"version": 1, "hosts": {"opencode": {}}})
    assert opencode.hosts["opencode"].user_mcp is False


def test_cursor_user_mcp_can_be_refused():
    config = parse_config({"version": 1, "hosts": {"cursor": {"user_mcp": False}}})
    assert not cursor_user_mcp_enabled(config)


def test_prefixed_name_is_stable():
    assert prefixed_name("wren") == "agentize-wren"
    assert prefixed_name("agentize-wren") == "agentize-wren"


def test_absolutize_directory(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    command = ("uv", "run", "--directory", "family/orch", "masstrade-agent")
    out = absolutize_command(command, root)
    assert Path(out[3]) == (root / "family/orch").resolve()


def test_render_keeps_foreign_keys_and_drops_stale_prefix(tmp_path: Path):
    existing = {
        "mcpServers": {
            "wren": {"command": "wren"},
            "agentize-old": {"command": "gone"},
            "orchestrator": {"command": "dup"},
        }
    }
    config = parse_config(yaml.safe_load(PARENT))
    wanted = collect_user_mcp_servers(tmp_path, config, config.default_profile)
    rendered = render_user_mcp(existing, wanted)
    servers = rendered["mcpServers"]
    assert "wren" in servers
    assert "agentize-old" not in servers
    assert "orchestrator" not in servers
    assert "agentize-orchestrator" in servers
    assert "agentize-atlassian" in servers


def test_collect_unions_child_yaml(tmp_path: Path):
    parent = tmp_path / "binder"
    child = parent / "masstrade-workspace"
    child.mkdir(parents=True)
    write(parent / "agentize.yaml", PARENT.replace("mcp: [orchestrator, atlassian]", "mcp: []"))
    write(
        parent / "mani.yaml",
        yaml.safe_dump({"projects": {"ws": {"path": "masstrade-workspace"}}}),
    )
    write(child / "agentize.yaml", PARENT)
    config = parse_config(yaml.safe_load((parent / "agentize.yaml").read_text(encoding="utf-8")))
    wanted = collect_user_mcp_servers(parent, config, config.default_profile)
    orch = wanted["agentize-orchestrator"]
    assert Path(orch.command[3]) == (child / "family/orch").resolve()


def test_inherit_only_grandchild_does_not_double_directory(tmp_path: Path):
    parent = tmp_path / "ws"
    family = parent / "family"
    erp = parent / "erp"
    family.mkdir(parents=True)
    erp.mkdir()
    write(parent / "agentize.yaml", PARENT)
    write(parent / ".agents" / "shared" / "style.mdc", "x\n")
    write(
        parent / "mani.yaml",
        yaml.safe_dump({"projects": {"erp": {"path": "erp"}, "family": {"path": "family"}}}),
    )
    config = parse_config(yaml.safe_load(PARENT))
    wanted = collect_user_mcp_servers(parent, config, config.default_profile)
    assert Path(wanted["agentize-orchestrator"].command[3]) == (
        parent / "family/orch"
    ).resolve()


def test_plan_and_strip_roundtrip(tmp_path: Path):
    path = tmp_path / ".cursor" / "mcp.json"
    write(path, json.dumps({"mcpServers": {"wren": {"command": "wren"}}}))
    config = parse_config(yaml.safe_load(PARENT))
    wanted = collect_user_mcp_servers(tmp_path, config, config.default_profile)
    plan = plan_user_mcp(wanted, path=path)
    assert plan.writes
    path.write_bytes(plan.writes[0].content)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "wren" in data["mcpServers"]
    assert any(name.startswith(PREFIX) for name in data["mcpServers"])
    assert strip_user_mcp_prefix(path=path)
    left = json.loads(path.read_text(encoding="utf-8"))["mcpServers"]
    assert list(left) == ["wren"]
