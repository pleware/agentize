"""Render the host-neutral `AGENTS.md` index.

Every host reads this file, so it carries no host layer — only shared plus the
profile. Prose outside the markers is the project's own and is never rewritten.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..config import Profile, identity_label
from ..resolve import ResolvedFile

FILE = "AGENTS.md"
BEGIN = "<!-- agentize:begin -->"
END = "<!-- agentize:end -->"
NOTE = "<!-- Managed by agentize. Edits between these markers are overwritten. -->"
RULE_SUFFIX = ".mdc"
HEADING = "## Project rules"
GENERATED = (
    "Do not edit `.cursor/rules/` files whose names start with `auto.` "
    "(including `auto.mt.`) — they are written by `agentize mount`."
)
QUALIFIED_NOTE = (
    "`agentize mount --profile-all` writes one file per identity: "
    "`auto.<identity>.<name>.mdc`."
)


def identity_heading(identity: Profile) -> str:
    """Section title for one identity's rules in the `AGENTS.md` index."""
    kind = "slug" if identity.origin == "agent" else "profile"
    return f"{identity_label(identity)} ({kind})"


def rules(resolved: Iterable[ResolvedFile]) -> tuple[ResolvedFile, ...]:
    """Only rule files are listed. The source tree also carries skills."""
    return tuple(item for item in resolved if item.key.lower().endswith(RULE_SUFFIX))


def render_block(resolved: Iterable[ResolvedFile], source: Path) -> str:
    lines = [BEGIN, NOTE, "", HEADING, "", GENERATED, ""]
    for item in rules(resolved):
        lines.append(f"- [{item.key}]({(source / item.path).as_posix()})")
    lines.append(END)
    return "\n".join(lines)


def render_block_all(
    groups: Iterable[tuple[str, tuple[ResolvedFile, ...]]], source: Path
) -> str:
    """One section per identity, so two identities' rule sets stay readable.

    The listed path is always the source; the emitted file is
    `auto.<identity>.<name>.mdc` in `.cursor/rules/`.
    """
    sections = list(groups)
    lines = [BEGIN, NOTE, "", HEADING, "", GENERATED]
    if len(sections) > 1:
        lines.append(QUALIFIED_NOTE)
    for heading, resolved in sections:
        lines.extend(["", f"### {heading}"])
        for item in rules(resolved):
            lines.append(f"- [{item.key}]({(source / item.path).as_posix()})")
    lines.append(END)
    return "\n".join(lines)


def merge(existing: str, block: str) -> str:
    text = existing.replace("\r\n", "\n")

    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        return f"{head}{block}{tail}"

    prose = text.rstrip("\n")
    return f"{prose}\n\n{block}\n" if prose else f"{block}\n"
