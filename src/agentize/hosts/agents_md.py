"""Render the host-neutral `AGENTS.md` index.

Every host reads this file, so it carries no host layer — only shared plus the
profile. Prose outside the markers is the project's own and is never rewritten.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..resolve import ResolvedFile

FILE = "AGENTS.md"
BEGIN = "<!-- agentize:begin -->"
END = "<!-- agentize:end -->"
NOTE = "<!-- Managed by agentize. Edits between these markers are overwritten. -->"
RULE_SUFFIX = ".mdc"
HEADING = "## Project rules"
GENERATED = (
    "Do not edit `.cursor/rules/` files whose names start with `auto.` "
    "(including `auto.mt.`). They are written by `agentize mount`."
)


def rules(resolved: Iterable[ResolvedFile]) -> tuple[ResolvedFile, ...]:
    """Only rule files are listed. The source tree also carries skills."""
    return tuple(item for item in resolved if item.key.lower().endswith(RULE_SUFFIX))


def render_block(resolved: Iterable[ResolvedFile], source: Path) -> str:
    lines = [BEGIN, NOTE, "", HEADING, "", GENERATED, ""]
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
