"""Resolve the project's own skills.

A skill is a directory holding `SKILL.md`, so the directory is the unit of
resolution. Merging files from two layers would build a skill whose `SKILL.md`
describes helpers that came from somewhere else, so the winning layer supplies
the whole thing or none of it.

Each host writes into a directory only that host reads, which is what keeps a
profile's skills from leaking sideways. Cursor and OpenCode use project
folders; Hermes uses the dedicated profile ``skills/`` tree. No skill is ever
installed into the directories several hosts scan in common (`.agents/skills`,
`.claude/skills`, `.codex/skills`), so there is nothing to clean up afterwards.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .errors import MountError
from .resolve import ResolvedFile

MARKER = "SKILL.md"
SEGMENT = "skills"
SHARED_LAYER = "shared"
DEFAULT_PREFIX = "agentize.auto.generated."


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


def skill_resolve_map(units: Iterable[str]) -> dict[str, str]:
    """Map a resolve listing path to the directory on disk.

    skillize writes ``<source>/skills/<name>/``. Layered source uses
    ``<source>/shared/skills/<name>/``. A root tree competes as shared so a
    real shared copy still wins, and ``item.path`` from resolve can be
    rewritten back to the files that exist.
    """
    mapping: dict[str, str] = {}
    for raw in units:
        unit = raw.replace("\\", "/")
        if unit.startswith(f"{SEGMENT}/") and unit.count("/") == 1:
            mapping.setdefault(f"{SHARED_LAYER}/{unit}", unit)
        else:
            mapping[unit] = unit
    return mapping


def emit_dir_name(name: str, prefix: str, qualifier: str | None = None) -> str:
    """`review` → `agentize.auto.generated.review`, or
    `agentize.auto.generated.human.review` when an identity is named.

    A skill already spelled with the prefix keeps its name: the author chose it.
    """
    if prefix and name.startswith(prefix):
        return name
    stem = f"{qualifier}.{name}" if qualifier else name
    return f"{prefix}{stem}"


def plan_skills(
    resolved: Iterable[ResolvedFile],
    prefix: str,
    selected: Iterable[str] = (),
    qualifier: str | None = None,
) -> tuple[Emitted, ...]:
    """Which skills to write, and under what directory name.

    An empty selection means every resolved skill. A profile that lists names
    narrows that set. `qualifier` is the identity label; two identities that
    resolve the same source under it are one entry, not a clash.
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

        dir_name = emit_dir_name(name, prefix, qualifier)
        clash = emitted.get(dir_name)
        if clash is not None:
            if clash.source == item.path:
                continue
            raise MountError(
                f"{clash.source} and {item.path} would both be written as {dir_name}. "
                "Skill directory names must be unique within a host."
            )
        emitted[dir_name] = Emitted(name=name, dir_name=dir_name, source=item.path)

    return tuple(emitted[key] for key in sorted(emitted))


def known_skill_names(units: Iterable[str]) -> frozenset[str]:
    """Every authored skill name across every layer and host.

    A name scoped to another host's private layer (``hosts/<host>/skills/``)
    is still a known name — it is simply not visible to every host. A mount
    should refuse only a name that exists nowhere, so the "unknown" check
    compares the identity's `skills` selection against this set, not against
    one host's resolved view.
    """
    return frozenset(name for unit in units if (name := skill_name(unit)) is not None)


def skill_name(unit: str) -> str | None:
    """The authored name of one skill unit, or `None` if it is not a skill.

    A unit is a directory holding `SKILL.md` (see `skill_units`), spelled as
    `skills/<name>`, `shared/skills/<name>`, `hosts/<host>/skills/<name>`,
    `profiles/<p>/skills/<name>`, or `agents/<a>/skills/<name>`.
    """
    clean = unit.replace("\\", "/")
    if clean.startswith(f"{SEGMENT}/"):
        name = clean[len(SEGMENT) + 1 :].split("/", 1)[0]
    elif f"/{SEGMENT}/" in clean:
        name = clean.split(f"/{SEGMENT}/", 1)[1].split("/", 1)[0]
    else:
        return None
    return name or None


def stale_dir_names(existing: Iterable[str], wanted: Iterable[str], prefix: str) -> tuple[str, ...]:
    """Emitted skill directories that are no longer resolved.

    Only prefixed names are candidates, so a hand-written skill sitting in the
    same directory is never removed.
    """
    keep = set(wanted)
    return tuple(sorted(name for name in existing if name.startswith(prefix) and name not in keep))
