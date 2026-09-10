from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import yaml

from agentize.cascade import (
    rebase_command,
    rebase_relpath,
    rebase_servers,
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
      command: [uv, run, --directory, family/orchestrator, family-agent]
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
    command = ("uv", "run", "--directory", "family/orch", "family-agent")
    assert rebase_command(command, parent, child) == (
        "uv",
        "run",
        "--directory",
        "../family/orch",
        "family-agent",
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
        "family-agent",
    ]
    assert "atlassian" in servers
    parents = yaml.safe_load((erp / ".agentize" / "parents.yaml").read_text(encoding="utf-8"))
    assert parents["parents"][0]["rel"] == ".."
    assert parents["parents"][0]["kind"] == "workspace"
    assert not (erp / "AGENTS.md").exists()
    leave = erp / ".cursor" / "rules" / "auto.do-not-edit.mdc"
    assert leave.is_file()
    assert "alwaysApply: true" in leave.read_text(encoding="utf-8")
    assert [path.name for path in (erp / ".cursor" / "rules").glob("*.mdc")] == [
        "auto.do-not-edit.mdc"
    ]


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
    assert (landing / ".cursor" / "rules" / "auto.do-not-edit.mdc").is_file()


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
    assert cursor_servers(ws)["orchestrator"]["args"][2] == "family/orchestrator"
    assert cursor_servers(erp)["orchestrator"]["args"][2] == "../family/orchestrator"
    chain = yaml.safe_load((erp / ".agentize" / "parents.yaml").read_text(encoding="utf-8"))
    assert [row["rel"] for row in chain["parents"]] == ["..", "../.."]


def test_mixed_origins_keep_separate_directory_roots(tmp_path: Path):
    """A binder-owned server and a child-owned server rebase from different roots."""
    binder = tmp_path / "binder"
    company = binder / "company"
    erp = company / "erp"
    erp.mkdir(parents=True)
    base = parse_config(
        {
            "version": 1,
            "mcp": {
                "servers": {
                    "shared": {
                        "command": ["uv", "run", "--directory", "tools/shared", "s"]
                    },
                    "orch": {
                        "command": ["uv", "run", "--directory", "family/orch", "o"]
                    },
                }
            },
        }
    )
    config = replace(
        base,
        servers={
            "shared": replace(base.servers["shared"], declared_at=binder.resolve()),
            "orch": replace(base.servers["orch"], declared_at=company.resolve()),
        },
    )
    at_company = rebase_servers(config, binder, company)
    assert at_company.servers["shared"].command[3] == "../tools/shared"
    assert at_company.servers["orch"].command[3] == "family/orch"
    at_erp = rebase_servers(config, company, erp)
    assert at_erp.servers["shared"].command[3] == "../../tools/shared"
    assert at_erp.servers["orch"].command[3] == "../family/orch"


def test_empty_parent_does_not_plant_empty_mcp_on_bare_child(tmp_path: Path):
    binder = tmp_path / "binder"
    pware = binder / "pware"
    pware.mkdir(parents=True)
    write(
        binder / "agentize.yaml",
        "version: 1\nhosts:\n  cursor: {}\nprofiles:\n  human:\n    default: true\n    mcp: []\n",
    )
    write(binder / ".agents" / "shared" / "style.mdc", "x\n")
    mani_projects(binder, pware="pware")

    assert main(["-C", str(binder), "mount"]) == 0
    assert not (pware / ".cursor" / "mcp.json").exists()
    assert (pware / ".agentize" / "parents.yaml").is_file()


def test_empty_inherit_list_refuses(tmp_path: Path):
    spec = parse_config({"version": 1, "inherit": []})
    assert spec.inherit.refuse
    assert not spec.inherit.allows("mcp")


def test_mount_check_writes_nothing(tmp_path: Path):
    """`--check` is a CI gate: it reports what is stale and creates nothing.

    The cascade used to prepare `.agentize/` in every child before it asked
    whether anything had changed, so a check-only run left a directory behind.
    """
    ws = tmp_path / "ws"
    erp = ws / "erp"
    write(ws / "agentize.yaml", PARENT)
    write(ws / ".agents" / "shared" / "style.mdc", "style\n")
    erp.mkdir()
    mani_projects(ws, erp="erp")

    assert main(["-C", str(ws), "mount", "--check"]) == 1

    assert not (ws / ".agentize").exists()
    assert not (ws / ".cursor").exists()
    assert not (ws / "AGENTS.md").exists()
    assert not (erp / ".agentize").exists()
    assert not (erp / ".cursor").exists()
