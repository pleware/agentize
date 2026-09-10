"""Shared `cascade/` rules descend from ancestors; the nearest owner wins."""

from __future__ import annotations

from pathlib import Path

import yaml

from agentize.cli import main

BINDER = """\
version: 1
source: .agents
hosts:
  cursor: {}
profiles:
  human: {default: true, mcp: []}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def rule_names(root: Path) -> list[str]:
    directory = root / ".cursor" / "rules"
    return sorted(item.name for item in directory.glob("*.mdc")) if directory.is_dir() else []


def test_a_binder_rule_descends_into_every_child(tmp_path: Path):
    ws = tmp_path / "ws"
    child = ws / "child"
    child.mkdir(parents=True)
    write(ws / "agentize.yaml", BINDER)
    write(
        ws / ".agents" / "cascade" / "git-index-flags.mdc",
        "---\ndescription: never hide a tracked file\nalwaysApply: true\n---\n\nDo the thing.\n",
    )
    write(ws / "mani.yaml", yaml.safe_dump({"projects": {"child": {"path": "child"}}}))

    assert main(["-C", str(ws), "mount"]) == 0

    assert "auto.git-index-flags.mdc" in rule_names(ws)
    assert "auto.git-index-flags.mdc" in rule_names(child)


def test_the_nearest_owner_wins_on_a_filename(tmp_path: Path):
    ws = tmp_path / "ws"
    child = ws / "child"
    child.mkdir(parents=True)
    write(ws / "agentize.yaml", BINDER)
    write(ws / ".agents" / "cascade" / "git-index-flags.mdc", "parent rule\n")
    write(ws / "mani.yaml", yaml.safe_dump({"projects": {"child": {"path": "child"}}}))
    write(child / "agentize.yaml", "version: 1\nsource: .agents\nhosts:\n  cursor: {}\n")
    write(child / ".agents" / "cascade" / "git-index-flags.mdc", "child rule\n")

    assert main(["-C", str(ws), "mount"]) == 0

    assert (
        ws / ".cursor" / "rules" / "auto.git-index-flags.mdc"
    ).read_text(encoding="utf-8") == "parent rule\n"
    assert (
        child / ".cursor" / "rules" / "auto.git-index-flags.mdc"
    ).read_text(encoding="utf-8") == "child rule\n"


def test_a_child_mount_keeps_the_inherited_rule(tmp_path: Path):
    ws = tmp_path / "ws"
    child = ws / "child"
    child.mkdir(parents=True)
    write(ws / "agentize.yaml", BINDER)
    write(
        ws / ".agents" / "cascade" / "git-index-flags.mdc",
        "---\ndescription: never hide a tracked file\nalwaysApply: true\n---\n\nDo the thing.\n",
    )
    write(ws / "mani.yaml", yaml.safe_dump({"projects": {"child": {"path": "child"}}}))

    assert main(["-C", str(ws), "mount"]) == 0
    # A child's own mount re-derives the rule from its ancestors and keeps it,
    # rather than pruning it as stale.
    assert main(["-C", str(child), "mount"]) == 0
    assert "auto.git-index-flags.mdc" in rule_names(child)


def test_mount_check_with_cascade_rules_still_writes_nothing(tmp_path: Path):
    ws = tmp_path / "ws"
    child = ws / "child"
    child.mkdir(parents=True)
    write(ws / "agentize.yaml", BINDER)
    write(ws / ".agents" / "cascade" / "git-index-flags.mdc", "---\nalwaysApply: true\n---\n\nx\n")
    write(ws / "mani.yaml", yaml.safe_dump({"projects": {"child": {"path": "child"}}}))

    assert main(["-C", str(ws), "mount", "--check"]) == 1

    assert not (ws / ".agentize").exists()
    assert not (ws / ".cursor").exists()
    assert not (child / ".agentize").exists()
    assert not (child / ".cursor").exists()
