from __future__ import annotations

from pathlib import Path

import pytest

from agentize.cli import main
from agentize.errors import MountError
from agentize.hosts.cursor import (
    GENERATED_RULE_NAME,
    Emitted,
    emit_name,
    plan_rules,
    stale_names,
)
from agentize.resolve import ResolvedFile

CONFIG = """\
version: 1
source: .agents
hosts:
  cursor:
    emit_prefix: agentize.auto.generated.
profiles:
  human:
    default: true
  agent: {}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    write(tmp_path / ".agents" / "shared" / "core" / "style.mdc", "shared style\n")
    return tmp_path


def rules_dir(project: Path) -> Path:
    return project / ".cursor" / "rules"


def emitted(project: Path) -> list[str]:
    directory = rules_dir(project)
    return sorted(item.name for item in directory.glob("*.mdc")) if directory.is_dir() else []


# --- naming and planning, no filesystem ---


def test_emit_name_flattens_and_prefixes():
    assert (
        emit_name("core/style.mdc", "agentize.auto.generated.")
        == "agentize.auto.generated.style.mdc"
    )


def test_emit_name_does_not_double_the_prefix():
    assert (
        emit_name("core/agentize.auto.generated.style.mdc", "agentize.auto.generated.")
        == "agentize.auto.generated.style.mdc"
    )


def test_non_rule_files_are_not_emitted():
    resolved = [ResolvedFile(key="notes.md", path="shared/notes.md", layer="shared")]
    assert plan_rules(resolved, "agentize.auto.generated.") == ()


def test_flattening_collision_is_an_error_not_a_silent_overwrite():
    resolved = [
        ResolvedFile(key="php/style.mdc", path="shared/php/style.mdc", layer="shared"),
        ResolvedFile(key="shell/style.mdc", path="shared/shell/style.mdc", layer="shared"),
    ]
    with pytest.raises(
        MountError, match="would both be written as agentize.auto.generated.style.mdc"
    ):
        plan_rules(resolved, "agentize.auto.generated.")


def test_only_prefixed_files_are_ever_stale():
    existing = [
        "agentize.auto.generated.gone.mdc",
        "agentize.auto.generated.kept.mdc",
        "handwritten.mdc",
    ]
    assert stale_names(
        existing, ["agentize.auto.generated.kept.mdc"], "agentize.auto.generated."
    ) == ("agentize.auto.generated.gone.mdc",)


def test_emitted_names_are_sorted():
    resolved = [
        ResolvedFile(key="z.mdc", path="shared/z.mdc", layer="shared"),
        ResolvedFile(key="a.mdc", path="shared/a.mdc", layer="shared"),
    ]
    assert plan_rules(resolved, "agentize.auto.generated.") == (
        Emitted("agentize.auto.generated.a.mdc", "shared/a.mdc"),
        Emitted("agentize.auto.generated.z.mdc", "shared/z.mdc"),
    )


def test_a_qualifier_marks_the_identity():
    assert (
        emit_name("core/style.mdc", "agentize.auto.generated.", "human")
        == "agentize.auto.generated.human.style.mdc"
    )

    resolved = [ResolvedFile(key="style.mdc", path="shared/style.mdc", layer="shared")]
    assert plan_rules(resolved, "agentize.auto.generated.", "human") == (
        Emitted("agentize.auto.generated.human.style.mdc", "shared/style.mdc"),
    )


# --- mount end to end ---


def test_mount_writes_generated_leave_alone_rule(project: Path):
    main(["-C", str(project), "mount"])
    path = rules_dir(project) / GENERATED_RULE_NAME
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "alwaysApply: true" in text
    assert "agentize.auto.generated." in text
    assert "agentize mount" in text


def test_source_rule_cannot_use_the_generated_name(project: Path, capsys):
    write(project / ".agents" / "shared" / "do-not-edit.mdc", "clash\n")
    assert main(["-C", str(project), "mount"]) == 1
    assert GENERATED_RULE_NAME in capsys.readouterr().err


def test_mount_writes_prefixed_rules(project: Path):
    assert main(["-C", str(project), "mount"]) == 0
    assert set(emitted(project)) == {GENERATED_RULE_NAME, "agentize.auto.generated.style.mdc"}
    assert (rules_dir(project) / "agentize.auto.generated.style.mdc").read_text(
        encoding="utf-8"
    ) == "shared style\n"


def test_profile_layer_overrides_shared(project: Path):
    write(project / ".agents" / "profiles" / "human" / "core" / "style.mdc", "human style\n")

    main(["-C", str(project), "mount"])

    assert set(emitted(project)) == {GENERATED_RULE_NAME, "agentize.auto.generated.style.mdc"}
    assert (rules_dir(project) / "agentize.auto.generated.style.mdc").read_text(
        encoding="utf-8"
    ) == "human style\n"


def test_profile_flag_selects_a_different_layer(project: Path):
    write(project / ".agents" / "profiles" / "agent" / "core" / "style.mdc", "agent style\n")

    main(["-C", str(project), "mount", "--profile", "agent"])

    assert (rules_dir(project) / "agentize.auto.generated.style.mdc").read_text(
        encoding="utf-8"
    ) == "agent style\n"


def test_removing_a_source_rule_deletes_the_emitted_file(project: Path):
    extra = write(project / ".agents" / "shared" / "extra.mdc", "extra\n")
    main(["-C", str(project), "mount"])
    assert set(emitted(project)) == {
        GENERATED_RULE_NAME,
        "agentize.auto.generated.extra.mdc",
        "agentize.auto.generated.style.mdc",
    }

    extra.unlink()
    main(["-C", str(project), "mount"])

    assert set(emitted(project)) == {GENERATED_RULE_NAME, "agentize.auto.generated.style.mdc"}


def test_handwritten_rule_survives(project: Path):
    handwritten = write(rules_dir(project) / "mine.mdc", "mine\n")

    main(["-C", str(project), "mount"])
    main(["-C", str(project), "mount"])

    assert handwritten.read_text(encoding="utf-8") == "mine\n"


def test_second_run_touches_nothing(project: Path):
    main(["-C", str(project), "mount"])
    before = (rules_dir(project) / "agentize.auto.generated.style.mdc").stat().st_mtime_ns

    main(["-C", str(project), "mount"])

    assert (rules_dir(project) / "agentize.auto.generated.style.mdc").stat().st_mtime_ns == before


def test_changed_source_is_rewritten(project: Path):
    main(["-C", str(project), "mount"])
    write(project / ".agents" / "shared" / "core" / "style.mdc", "changed\n")

    main(["-C", str(project), "mount"])

    assert (rules_dir(project) / "agentize.auto.generated.style.mdc").read_text(
        encoding="utf-8"
    ) == "changed\n"


def test_unknown_profile_fails_with_a_message(project: Path, capsys):
    assert main(["-C", str(project), "mount", "--profile", "robot"]) == 1
    assert "unknown profile 'robot'" in capsys.readouterr().err


# --- mount --check ---


def test_check_passes_on_a_clean_tree(project: Path):
    main(["-C", str(project), "mount"])
    assert main(["-C", str(project), "mount", "--check"]) == 0


def test_check_fails_and_names_the_missing_file(project: Path, capsys):
    assert main(["-C", str(project), "mount", "--check"]) == 1

    captured = capsys.readouterr()
    assert "create .cursor/rules/agentize.auto.generated.style.mdc" in captured.out
    assert f"create .cursor/rules/{GENERATED_RULE_NAME}" in captured.out
    assert "out of date" in captured.err


def test_check_never_writes(project: Path):
    main(["-C", str(project), "mount", "--check"])
    assert not rules_dir(project).exists()


def test_check_does_not_touch_an_existing_stale_file(project: Path):
    main(["-C", str(project), "mount"])
    write(project / ".agents" / "shared" / "core" / "style.mdc", "changed\n")
    target = rules_dir(project) / "agentize.auto.generated.style.mdc"
    before = target.stat().st_mtime_ns

    assert main(["-C", str(project), "mount", "--check"]) == 1

    assert target.stat().st_mtime_ns == before
    assert target.read_text(encoding="utf-8") == "shared style\n"


def test_check_reports_a_stale_deletion(project: Path, capsys):
    extra = write(project / ".agents" / "shared" / "extra.mdc", "extra\n")
    main(["-C", str(project), "mount"])
    extra.unlink()

    assert main(["-C", str(project), "mount", "--check"]) == 1
    assert "delete .cursor/rules/agentize.auto.generated.extra.mdc" in capsys.readouterr().out
