from __future__ import annotations

import json
from pathlib import Path

import yaml

from agentize.cascade import (
    rebase_command,
    rebase_relpath,
)
from agentize.cli import main
from agentize.config import parse_config

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
      command: [uv, run, --directory, family/orchestrator, masstrade-agent]
    atlassian:
      command: [uvx, mcp-atlassian]
"""

CHILD_FILTER = """\
version: 1
source: .agents
hosts:
  cursor: {}
profiles:
  human:
    default: true
    mcp: [atlassian]
mcp:
  servers:
    atlassian:
      command: [uvx, mcp-atlassian]
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def mani_projects(root: Path, **paths: str) -> None:
    projects = {name: {"path": rel} for name, rel in paths.items()}
    write(root / "mani.yaml", yaml.safe_dump({"projects": projects}))


def cursor_servers(root: Path) -> dict:
    data = json.loads((root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    return data["mcpServers"]


def test_rebase_directory_flag(tmp_path: Path):
    parent = tmp_path / "ws"
    child = parent / "erp"
    child.mkdir(parents=True)
    command = ("uv", "run", "--directory", "family/orch", "masstrade-agent")
    assert rebase_command(command, parent, child) == (
        "uv",
        "run",
        "--directory",
        "../family/orch",
        "masstrade-agent",
    )


def test_rebase_leaves_absolute_paths(tmp_path: Path):
    parent = tmp_path / "ws"
    child = parent / "erp"
    child.mkdir(parents=True)
    absolute = str((parent / "family" / "orch").resolve())
    assert rebase_relpath(absolute, parent, child) == absolute


def test_mount_plants_mcp_on_existing_children(tmp_path: Path):
    ws = tmp_path / "ws"
    erp = ws / "erp"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    erp.mkdir()
    mani_projects(ws, self=".", erp="erp", missing="no-such-dir")

    assert main(["-C", str(ws), "mount"]) == 0

    servers = cursor_servers(erp)
    assert servers["orchestrator"]["args"] == [
        "run",
        "--directory",
        "../family/orchestrator",
        "masstrade-agent",
    ]
    assert "atlassian" in servers
    parents = yaml.safe_load((erp / ".agentize" / "parents.yaml").read_text(encoding="utf-8"))
    assert parents["parents"][0]["rel"] == ".."
    assert parents["parents"][0]["kind"] == "workspace"
    assert not (erp / "AGENTS.md").exists()
    assert not (erp / ".cursor" / "rules").exists()


def test_missing_child_is_skipped_not_an_error(tmp_path: Path):
    ws = tmp_path / "ws"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    mani_projects(ws, ghost="ghost")
    assert main(["-C", str(ws), "mount"]) == 0
    assert not (ws / "ghost").exists()


def test_inherit_false_skips_mcp(tmp_path: Path):
    ws = tmp_path / "ws"
    landing = ws / "landing"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    write(landing / "agentize.yaml", "version: 1\ninherit: false\n")
    mani_projects(ws, landing="landing")

    assert main(["-C", str(ws), "mount"]) == 0
    assert not (landing / ".cursor" / "mcp.json").exists()
    assert (landing / ".agentize" / "parents.yaml").is_file()


def test_child_mcp_list_filters_parent_servers(tmp_path: Path):
    ws = tmp_path / "ws"
    react = ws / "react"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    write(react / "agentize.yaml", CHILD_FILTER)
    write(react / ".agents" / "shared" / "style.mdc", "react\n")
    mani_projects(ws, react="react")

    assert main(["-C", str(ws), "mount"]) == 0
    assert list(cursor_servers(react)) == ["atlassian"]


def test_mount_in_child_without_yaml_inherits(tmp_path: Path):
    ws = tmp_path / "ws"
    erp = ws / "erp"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    erp.mkdir()
    mani_projects(ws, erp="erp")

    assert main(["-C", str(erp), "mount"]) == 0
    assert "orchestrator" in cursor_servers(erp)
    assert cursor_servers(erp)["orchestrator"]["args"][2] == "../family/orchestrator"


def test_recursive_mani_walk(tmp_path: Path):
    binder = tmp_path / "binder"
    ws = binder / "company"
    erp = ws / "erp"
    write(
        binder / "agentize.yaml",
        "version: 1\nhosts:\n  cursor: {}\nprofiles:\n  human:\n    default: true\n    mcp: []\n",
    )
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    erp.mkdir(parents=True)
    write(binder / ".agents" / "shared" / "style.mdc", "binder\n")
    mani_projects(binder, company="company")
    mani_projects(ws, erp="erp")
    write(ws / "ignite.toml", '[workspace-tree]\nkind = "workspace"\n')

    assert main(["-C", str(binder), "mount"]) == 0
    assert "orchestrator" in cursor_servers(erp)
    chain = yaml.safe_load((erp / ".agentize" / "parents.yaml").read_text(encoding="utf-8"))
    assert [row["rel"] for row in chain["parents"]] == ["..", "../.."]


def test_empty_inherit_list_refuses(tmp_path: Path):
    spec = parse_config({"version": 1, "inherit": []})
    assert spec.inherit.refuse
    assert not spec.inherit.allows("mcp")
