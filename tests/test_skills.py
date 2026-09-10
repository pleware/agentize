from __future__ import annotations

from pathlib import Path

import pytest

from agentize.cli import main
from agentize.errors import MountError
from agentize.resolve import ResolvedFile
from agentize.skills import (
    known_skill_names,
    plan_skills,
    skill_resolve_map,
    skill_units,
    stale_dir_names,
)

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
  agent:
    skills: [review]
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    return tmp_path


def resolved(*pairs: tuple[str, str]) -> tuple[ResolvedFile, ...]:
    return tuple(
        ResolvedFile(key=key, path=path, layer=path.rsplit("/", 2)[0]) for key, path in pairs
    )


def test_skill_units_finds_directories_holding_a_marker():
    listing = (
        "shared/skills/review/SKILL.md",
        "shared/skills/review/checklist.md",
        "shared/core/style.mdc",
        "profiles/agent/skills/deploy/SKILL.md",
    )
    assert skill_units(listing) == ("profiles/agent/skills/deploy", "shared/skills/review")


def test_skillize_root_trees_compete_as_shared():
    assert skill_resolve_map(("skills/review",)) == {"shared/skills/review": "skills/review"}


def test_a_shared_copy_wins_the_disk_path():
    assert skill_resolve_map(("skills/review", "shared/skills/review")) == {
        "shared/skills/review": "shared/skills/review"
    }


def test_a_directory_without_the_marker_is_not_a_skill():
    assert skill_units(("shared/skills/review/notes.md",)) == ()


def test_the_prefix_is_applied_once():
    items = resolved(("skills/review", "shared/skills/review"))
    assert (
        plan_skills(items, "agentize.auto.generated.")[0].dir_name
        == "agentize.auto.generated.review"
    )

    already = resolved(
        ("skills/agentize.auto.generated.review", "shared/skills/agentize.auto.generated.review")
    )
    assert (
        plan_skills(already, "agentize.auto.generated.")[0].dir_name
        == "agentize.auto.generated.review"
    )


def test_a_qualifier_marks_the_identity():
    items = resolved(("skills/review", "shared/skills/review"))

    assert (
        plan_skills(items, "agentize.auto.generated.", (), "human")[0].dir_name
        == "agentize.auto.generated.human.review"
    )
    assert plan_skills(items, "agentize.auto.generated.", (), "agent")[0].name == "review"


def test_an_empty_selection_means_every_skill():
    items = resolved(
        ("skills/review", "shared/skills/review"),
        ("skills/deploy", "shared/skills/deploy"),
    )
    assert [item.name for item in plan_skills(items, "agentize.auto.generated.")] == [
        "deploy",
        "review",
    ]


def test_a_profile_selection_narrows_the_set():
    items = resolved(
        ("skills/review", "shared/skills/review"),
        ("skills/deploy", "shared/skills/deploy"),
    )
    assert [item.name for item in plan_skills(items, "agentize.auto.generated.", ["review"])] == [
        "review"
    ]


def test_a_rule_is_not_mistaken_for_a_skill():
    items = resolved(("core/style.mdc", "shared/core/style.mdc"))
    assert plan_skills(items, "agentize.auto.generated.") == ()


def test_known_skill_names_span_layers():
    units = (
        "skills/review",
        "shared/skills/deploy",
        "hosts/cursor/skills/graphify",
        "profiles/agent/skills/release",
    )
    assert known_skill_names(units) == {"review", "deploy", "graphify", "release"}


def test_stale_directories_ignore_hand_written_ones():
    existing = ("agentize.auto.generated.review", "agentize.auto.generated.deploy", "mine")
    assert stale_dir_names(
        existing, ["agentize.auto.generated.review"], "agentize.auto.generated."
    ) == ("agentize.auto.generated.deploy",)


def test_a_whole_skill_directory_is_copied(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")
    write(project / ".agents/shared/skills/review/checklist.md", "one\n")

    assert main(["-C", str(project), "mount"]) == 0

    emitted = project / ".cursor/skills/agentize.auto.generated.review"
    assert (emitted / "SKILL.md").read_text(encoding="utf-8") == "# review\n"
    assert (emitted / "checklist.md").read_text(encoding="utf-8") == "one\n"


def test_skillize_root_skills_are_copied(project: Path):
    write(project / ".agents/skills/review/SKILL.md", "# review\n")

    assert main(["-C", str(project), "mount"]) == 0

    assert (project / ".cursor/skills/agentize.auto.generated.review/SKILL.md").read_text(
        encoding="utf-8"
    ) == "# review\n"


def test_shared_layer_beats_a_skillize_root_skill(project: Path):
    write(project / ".agents/skills/review/SKILL.md", "# skillize\n")
    write(project / ".agents/shared/skills/review/SKILL.md", "# shared\n")

    main(["-C", str(project), "mount"])

    assert (project / ".cursor/skills/agentize.auto.generated.review/SKILL.md").read_text(
        encoding="utf-8"
    ) == "# shared\n"


def test_each_host_gets_its_own_copy(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")

    main(["-C", str(project), "mount"])

    assert (project / ".cursor/skills/agentize.auto.generated.review/SKILL.md").is_file()
    assert (project / ".opencode/skills/agentize.auto.generated.review/SKILL.md").is_file()


def test_skills_never_land_in_a_shared_directory(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")

    main(["-C", str(project), "mount"])

    for shared in (".agents/skills", ".claude/skills", ".codex/skills"):
        assert not (project / shared).exists()


def test_the_profile_layer_wins_whole(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# shared\n")
    write(project / ".agents/shared/skills/review/extra.md", "shared helper\n")
    write(project / ".agents/profiles/agent/skills/review/SKILL.md", "# agent\n")

    main(["-C", str(project), "mount", "--profile", "agent"])

    emitted = project / ".cursor/skills/agentize.auto.generated.review"
    assert (emitted / "SKILL.md").read_text(encoding="utf-8") == "# agent\n"
    assert not (emitted / "extra.md").exists()


def test_a_profile_selection_excludes_the_rest(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")
    write(project / ".agents/shared/skills/deploy/SKILL.md", "# deploy\n")

    main(["-C", str(project), "mount", "--profile", "agent"])

    assert (project / ".cursor/skills/agentize.auto.generated.review").is_dir()
    assert not (project / ".cursor/skills/agentize.auto.generated.deploy").exists()


def test_removing_a_source_skill_deletes_the_emitted_tree(project: Path):
    skill = project / ".agents/shared/skills/review"
    write(skill / "SKILL.md", "# review\n")
    main(["-C", str(project), "mount"])
    assert (project / ".cursor/skills/agentize.auto.generated.review").is_dir()

    (skill / "SKILL.md").unlink()
    skill.rmdir()
    main(["-C", str(project), "mount"])

    assert not (project / ".cursor/skills/agentize.auto.generated.review").exists()


def test_a_file_dropped_from_a_live_skill_is_removed(project: Path):
    skill = project / ".agents/shared/skills/review"
    write(skill / "SKILL.md", "# review\n")
    write(skill / "checklist.md", "one\n")
    main(["-C", str(project), "mount"])

    (skill / "checklist.md").unlink()
    main(["-C", str(project), "mount"])

    assert (project / ".cursor/skills/agentize.auto.generated.review/SKILL.md").is_file()
    assert not (project / ".cursor/skills/agentize.auto.generated.review/checklist.md").exists()


def test_a_hand_written_skill_survives(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")
    write(project / ".cursor/skills/mine/SKILL.md", "# mine\n")

    main(["-C", str(project), "mount"])
    main(["-C", str(project), "mount"])

    assert (project / ".cursor/skills/mine/SKILL.md").read_text(encoding="utf-8") == "# mine\n"


def test_a_second_mount_touches_nothing(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")
    main(["-C", str(project), "mount"])

    emitted = project / ".cursor/skills/agentize.auto.generated.review/SKILL.md"
    before = emitted.stat().st_mtime_ns

    assert main(["-C", str(project), "mount"]) == 0
    assert emitted.stat().st_mtime_ns == before


def test_check_reports_a_missing_skill(project: Path):
    write(project / ".agents/shared/skills/review/SKILL.md", "# review\n")

    assert main(["-C", str(project), "mount", "--check"]) == 1
    assert not (project / ".cursor/skills").exists()


def test_a_profile_asking_for_an_absent_skill_fails(project: Path, capsys):
    write(project / ".agents/shared/skills/deploy/SKILL.md", "# deploy\n")

    assert main(["-C", str(project), "mount", "--profile", "agent"]) == 1
    assert "review" in capsys.readouterr().err


def test_two_layers_cannot_collide_after_prefixing():
    items = resolved(
        ("skills/review", "shared/skills/review"),
        ("skills/agentize.auto.generated.review", "shared/skills/agentize.auto.generated.review"),
    )
    with pytest.raises(MountError, match="would both be written"):
        plan_skills(items, "agentize.auto.generated.")
