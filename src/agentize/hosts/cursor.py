"""Render resolved rules into `.cursor/rules`.

Cursor's rules directory is flat, so an emitted name is the source file's base
name carrying the prefix. The prefix is what makes pruning safe: agentize deletes
only files it could have written, and never touches hand-written rules.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ..config import McpServer
from ..errors import MountError
from ..resolve import ResolvedFile

RULES_DIR = ".cursor/rules"
RULE_SUFFIX = ".mdc"
DEFAULT_PREFIX = "auto."
# Always this filename, even when emit_prefix is longer than `auto.`
# (for example `auto.mt.`). Pruning still keys off emit_prefix, so a
# longer prefix will not delete this file.
GENERATED_RULE_STEM = "do-not-edit"
GENERATED_RULE_NAME = f"{DEFAULT_PREFIX}{GENERATED_RULE_STEM}{RULE_SUFFIX}"
GENERATED_RULE_TEXT = """\
---
description: Do not edit agentize-generated Cursor rules (auto.* filenames).
globs: .cursor/rules/auto*
alwaysApply: true
---

# Generated Cursor rules

Do not edit, move, or delete files in `.cursor/rules/` whose names start
with `auto.` — including `auto.mt.`. `agentize mount` writes them from the
`source:` tree in `agentize.yaml` (usually `.agents/`).

To change a generated rule, edit the source file, then run
`agentize mount`. Do not patch the emitted copy.

The same prefix marks skills agentize copies into `.cursor/skills/` and
`.opencode/skills/`. Leave those directories alone too.
"""

SKILLS_DIR = ".cursor/skills"

MCP_FILE = ".cursor/mcp.json"
MCP_KEY = "mcpServers"


@dataclass(frozen=True)
class Emitted:
    name: str
    source: str


def generated_rule_path(project_root: Path) -> Path:
    return project_root / RULES_DIR / GENERATED_RULE_NAME


def generated_rule_bytes() -> bytes:
    return GENERATED_RULE_TEXT.encode("utf-8")


def emit_name(key: str, prefix: str, qualifier: str | None = None) -> str:
    """`core/style.mdc` → `auto.style.mdc`, or `auto.human.style.mdc`.

    `qualifier` is the identity label, used when one directory holds every
    declared identity's rules.
    """
    base = PurePosixPath(key).name
    if base.lower().endswith(RULE_SUFFIX):
        base = base[: -len(RULE_SUFFIX)]
    if prefix and base.startswith(prefix):
        return f"{base}{RULE_SUFFIX}"
    stem = f"{qualifier}.{base}" if qualifier else base
    return f"{prefix}{stem}{RULE_SUFFIX}"


def plan_rules(
    resolved: Iterable[ResolvedFile], prefix: str, qualifier: str | None = None
) -> tuple[Emitted, ...]:
    emitted: dict[str, Emitted] = {}
    for item in resolved:
        if not item.key.lower().endswith(RULE_SUFFIX):
            continue
        name = emit_name(item.key, prefix, qualifier)
        clash = emitted.get(name)
        if clash is not None:
            if clash.source == item.path:
                continue
            raise MountError(
                f"{clash.source} and {item.path} would both be written as {name}. "
                "Cursor's rules directory is flat, so rule file names must be unique."
            )
        emitted[name] = Emitted(name=name, source=item.path)
    return tuple(emitted[name] for name in sorted(emitted))


def stale_names(existing: Iterable[str], wanted: Iterable[str], prefix: str) -> tuple[str, ...]:
    keep = set(wanted)
    return tuple(sorted(name for name in existing if name.startswith(prefix) and name not in keep))


def mcp_entry(server: McpServer) -> dict[str, Any]:
    if server.is_remote:
        entry: dict[str, Any] = {"url": server.url}
        if server.headers:
            entry["headers"] = dict(server.headers)
        return entry

    entry = {"type": "stdio", "command": server.command[0]}
    if len(server.command) > 1:
        entry["args"] = list(server.command[1:])
    if server.env:
        entry["env"] = dict(server.env)
    return entry


def render_mcp(existing: dict[str, Any], servers: Iterable[McpServer]) -> str:
    data = dict(existing)
    data[MCP_KEY] = {server.name: mcp_entry(server) for server in servers}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
