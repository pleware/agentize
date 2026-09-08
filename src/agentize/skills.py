"""Resolve the project's own skills.

A skill is a directory holding `SKILL.md`, so the directory is the unit of
resolution. Merging files from two layers would build a skill whose `SKILL.md`
describes helpers that came from somewhere else, so the winning layer supplies
the whole thing or none of it.

Each host writes into a directory only that host reads, which is what keeps a
profile's skills from leaking sideways. No skill is ever installed into the
directories several hosts scan in common (`.agents/skills`, `.claude/skills`,
`.codex/skills`), so there is nothing to clean up afterwards.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .errors import MountError
from .resolve import ResolvedFile

MARKER = "SKILL.md"
SEGMENT = "skills"
DEFAULT_PREFIX = "auto."


@dataclass(frozen=True)
class Emitted:
    name: str
    """The skill's name as authored."""

    dir_name: str
    """The directory written into the host, carrying the prefix."""

    source: str
    """The skill directory, relative to the source root."""


def skill_units(listing: Iterable[str]) -> tuple[str, ...]:
    """Every directory in a file listing that holds a `SKILL.md`.

    Feeding these to the resolver in place of files makes the directory the unit
    the layers compete over, at no cost in new resolution logic.
    """
    suffix = f"/{MARKER}"
    units = {
        path[: -len(suffix)]
        for path in (raw.replace("\\", "/") for raw in listing)
        if path.endswith(suffix)
    }
    return tuple(sorted(units))


def emit_dir_name(name: str, prefix: str) -> str:
    if prefix and name.startswith(prefix):
        return name
    return f"{prefix}{name}"


def plan_skills(
    resolved: Iterable[ResolvedFile], prefix: str, selected: Iterable[str] = ()
) -> tuple[Emitted, ...]:
    """Which skills to write, and under what directory name.

    An empty selection means every resolved skill. A profile that lists names
    narrows that set.
    """
    wanted = set(selected)
    emitted: dict[str, Emitted] = {}

    for item in resolved:
        parts = item.key.split("/")
        if len(parts) != 2 or parts[0] != SEGMENT:
            continue
        name = parts[1]
        if wanted and name not in wanted:
            continue

        dir_name = emit_dir_name(name, prefix)
        clash = emitted.get(dir_name)
        if clash is not None:
            raise MountError(
                f"{clash.source} and {item.path} would both be written as {dir_name}. "
                "Skill directory names must be unique within a host."
            )
        emitted[dir_name] = Emitted(name=name, dir_name=dir_name, source=item.path)

    return tuple(emitted[key] for key in sorted(emitted))


def unknown_names(resolved: Iterable[ResolvedFile], selected: Iterable[str]) -> tuple[str, ...]:
    """Names a profile asks for that no layer provides.

    Silently emitting nothing would read as "this profile has no skills" rather
    than "that skill does not exist".
    """
    available = {
        item.key.split("/")[1]
        for item in resolved
        if item.key.startswith(f"{SEGMENT}/") and item.key.count("/") == 1
    }
    return tuple(sorted(name for name in selected if name not in available))


def stale_dir_names(
    existing: Iterable[str], wanted: Iterable[str], prefix: str
) -> tuple[str, ...]:
    """Emitted skill directories that are no longer resolved.

    Only prefixed names are candidates, so a hand-written skill sitting in the
    same directory is never removed.
    """
    keep = set(wanted)
    return tuple(sorted(name for name in existing if name.startswith(prefix) and name not in keep))
