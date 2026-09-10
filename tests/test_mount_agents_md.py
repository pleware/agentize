from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.hosts import agents_md
from agentize.hosts.opencode import instruction_paths
from agentize.resolve import ResolvedFile

CONFIG = """\
version: 1
source: .agents
hosts:
  cursor:
    emit_prefix: agentize.auto.generated.
  opencode: {}
profiles:
  human:
    default: true
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    write(tmp_path / ".agents" / "shared" / "core" / "style.mdc", "shared style\n")
    write(tmp_path / ".agents" / "shared" / "php" / "types.mdc", "types\n")
    return tmp_path


# --- merging, no filesystem ---


def test_block_is_appended_to_an_empty_file():
    merged = agents_md.merge("", "BLOCK")
    assert merged == "BLOCK\n"


def test_handwritten_prose_is_kept_above_the_block():
    merged = agents_md.merge("# My project\n\nSome prose.\n", "BLOCK")
    assert merged == "# My project\n\nSome prose.\n\nBLOCK\n"


def test_an_existing_block_is_replaced_in_place():
    existing = f"Above.\n\n{agents_md.BEGIN}\nold\n{agents_md.END}\n\nBelow.\n"
    block = f"{agents_md.BEGIN}\nnew\n{agents_md.END}"

    merged = agents_md.merge(existing, block)

    assert "old" not in merged
    assert "new" in merged
    assert merged.startswith("Above.\n")
    assert merged.endswith("Below.\n")


def test_windows_line_endings_are_normalised():
    merged = agents_md.merge("# Title\r\n", "BLOCK")
    assert "\r" not in merged


def test_merging_twice_is_stable():
    block = f"{agents_md.BEGIN}\nx\n{agents_md.END}"
    once = agents_md.merge("Prose.\n", block)
    assert agents_md.merge(once, block) == once


def test_only_rules_are_listed():
    resolved = [
        ResolvedFile(key="a.mdc", path="shared/a.mdc", layer="shared"),
        ResolvedFile(key="notes.md", path="shared/notes.md", layer="shared"),
    ]
    block = agents_md.render_block(resolved, Path(".agents"))
    assert "shared/a.mdc" in block
    assert "notes.md" not in block
    assert "Do not edit `.cursor/rules/`" in block


# --- mount end to end ---


def test_agents_md_lists_the_resolved_rules(project: Path):
    assert main(["-C", str(project), "mount"]) == 0

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "- [core/style.mdc](.agents/shared/core/style.mdc)" in text
    assert "- [php/types.mdc](.agents/shared/php/types.mdc)" in text
    assert "Do not edit `.cursor/rules/`" in text


def test_agents_md_ignores_the_host_layer(project: Path):
    write(project / ".agents" / "hosts" / "cursor" / "only-cursor.mdc", "cursor\n")

    main(["-C", str(project), "mount"])

    assert "only-cursor.mdc" not in (project / "AGENTS.md").read_text(encoding="utf-8")


def test_agents_md_takes_the_profile_layer(project: Path):
    write(project / ".agents" / "profiles" / "human" / "core" / "style.mdc", "human\n")

    main(["-C", str(project), "mount"])

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "(.agents/profiles/human/core/style.mdc)" in text
    assert "(.agents/shared/core/style.mdc)" not in text


def test_existing_prose_survives_a_mount(project: Path):
    write(project / "AGENTS.md", "# House rules\n\nRead this first.\n")

    main(["-C", str(project), "mount"])

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert text.startswith("# House rules\n\nRead this first.\n")
    assert agents_md.BEGIN in text


def test_opencode_lists_the_winning_files_only(project: Path):
    write(project / ".agents" / "profiles" / "human" / "core" / "style.mdc", "human\n")

    main(["-C", str(project), "mount"])

    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert data["instructions"] == [
        ".agents/profiles/human/core/style.mdc",
        ".agents/shared/php/types.mdc",
    ]


def test_opencode_sees_its_own_host_layer(project: Path):
    write(project / ".agents" / "hosts" / "opencode" / "extra.mdc", "extra\n")

    main(["-C", str(project), "mount"])

    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert ".agents/hosts/opencode/extra.mdc" in data["instructions"]


def test_unrelated_opencode_keys_are_preserved(project: Path):
    write(project / "opencode.json", json.dumps({"theme": "dark", "instructions": ["old.mdc"]}))

    main(["-C", str(project), "mount"])

    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert "old.mdc" not in data["instructions"]


def test_broken_opencode_json_is_reported(project: Path, capsys):
    write(project / "opencode.json", "{ not json")

    assert main(["-C", str(project), "mount"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_instruction_paths_match_the_agents_md_listing(project: Path):
    main(["-C", str(project), "mount"])

    data = json.loads((project / "opencode.json").read_text(encoding="utf-8"))
    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    for path in data["instructions"]:
        assert f"({path})" in text


def test_mount_is_idempotent_across_all_targets(project: Path):
    main(["-C", str(project), "mount"])
    stamps = {
        path: path.stat().st_mtime_ns for path in (project / "AGENTS.md", project / "opencode.json")
    }

    main(["-C", str(project), "mount"])

    for path, before in stamps.items():
        assert path.stat().st_mtime_ns == before


def test_check_covers_agents_md_and_opencode(project: Path, capsys):
    assert main(["-C", str(project), "mount", "--check"]) == 1

    out = capsys.readouterr().out
    assert "create AGENTS.md" in out
    assert "create opencode.json" in out
    assert not (project / "AGENTS.md").exists()


def test_instruction_paths_skip_non_rules():
    resolved = [
        ResolvedFile(key="a.mdc", path="shared/a.mdc", layer="shared"),
        ResolvedFile(key="notes.md", path="shared/notes.md", layer="shared"),
    ]
    assert instruction_paths(resolved, Path(".agents")) == [".agents/shared/a.mdc"]
