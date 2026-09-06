"""Render OpenCode's `opencode.json`.

OpenCode takes an explicit list of instruction files, so agentize lists the
resolved winners directly and copies nothing. A glob could not express a profile
overriding a shared rule — it would match both.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import McpServer
from ..resolve import ResolvedFile

CONFIG_FILE = "opencode.json"
INSTRUCTIONS_KEY = "instructions"
MCP_KEY = "mcp"
PLUGIN_KEY = "plugin"
RULE_SUFFIX = ".mdc"

# Short names we accept in agentize.yaml. The value is what OpenCode puts on npm.
KNOWN_PLUGINS = {
    "oh-my-openagent": "oh-my-openagent",
    "omo": "oh-my-openagent",
}

SKILLS_DIR = ".opencode/skills"
"""Read by OpenCode and by nothing else. Cursor scans `.cursor`, `.agents`,
`.claude` and `.codex`, so writing here keeps the two hosts' skills apart."""


def instruction_paths(resolved: Iterable[ResolvedFile], source: Path) -> list[str]:
    return [
        (source / item.path).as_posix()
        for item in resolved
        if item.key.lower().endswith(RULE_SUFFIX)
    ]


def plugin_specs(names: Iterable[str]) -> list[str]:
    """Resolve aliases, keep order, drop duplicates.

    Unknown names pass through as npm specs (`pkg`, `pkg@1.2.3`). We do not
    install them — OpenCode fetches `plugin` entries itself at startup.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        spec = KNOWN_PLUGINS.get(raw, raw)
        if spec in seen:
            continue
        seen.add(spec)
        out.append(spec)
    return out


def mcp_entry(server: McpServer) -> dict[str, Any]:
    if server.is_remote:
        entry: dict[str, Any] = {"type": "remote", "url": server.url, "enabled": True}
        if server.headers:
            entry["headers"] = dict(server.headers)
        return entry

    entry = {"type": "local", "command": list(server.command), "enabled": True}
    if server.env:
        entry["environment"] = dict(server.env)
    return entry


def render_config(
    existing: dict[str, Any],
    resolved: Iterable[ResolvedFile],
    servers: Iterable[McpServer],
    source: Path,
    plugins: Iterable[str] = (),
) -> str:
    data = dict(existing)
    data[INSTRUCTIONS_KEY] = instruction_paths(resolved, source)
    data[MCP_KEY] = {server.name: mcp_entry(server) for server in servers}
    data[PLUGIN_KEY] = plugin_specs(plugins)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
