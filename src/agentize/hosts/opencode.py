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

from ..config import LspServer, McpServer
from ..resolve import ResolvedFile

CONFIG_FILE = "opencode.json"
TUI_FILE = "tui.json"
TUI_SCHEMA = "https://opencode.ai/tui.json"
INSTRUCTIONS_KEY = "instructions"
MCP_KEY = "mcp"
PLUGIN_KEY = "plugin"
LSP_KEY = "lsp"
PERMISSION_KEY = "permission"
RULE_SUFFIX = ".mdc"

# Short names we accept in agentize.yaml. The value is what OpenCode puts on npm.
KNOWN_PLUGINS = {
    "oh-my-openagent": "oh-my-openagent",
    "omo": "oh-my-openagent",
    "opencode-extended-sidebar": "opencode-extended-sidebar",
    "oes": "opencode-extended-sidebar",
}

# TUI-only packages belong in tui.json. Everything else stays on opencode.json.
TUI_PLUGINS = frozenset({"opencode-extended-sidebar"})

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


def tui_plugin_specs(names: Iterable[str]) -> list[str]:
    return [spec for spec in plugin_specs(names) if spec in TUI_PLUGINS]


def server_plugin_specs(names: Iterable[str]) -> list[str]:
    return [spec for spec in plugin_specs(names) if spec not in TUI_PLUGINS]


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


def lsp_entry(server: LspServer) -> dict[str, Any]:
    if server.disabled:
        return {"disabled": True}
    entry: dict[str, Any] = {"command": list(server.command)}
    if server.extensions:
        entry["extensions"] = list(server.extensions)
    if server.env:
        entry["env"] = dict(server.env)
    if server.initialization:
        entry["initialization"] = dict(server.initialization)
    return entry


def render_lsp(payload: bool | dict[str, LspServer]) -> bool | dict[str, Any]:
    if isinstance(payload, bool):
        return payload
    return {name: lsp_entry(server) for name, server in payload.items()}


def render_config(
    existing: dict[str, Any],
    resolved: Iterable[ResolvedFile],
    servers: Iterable[McpServer],
    source: Path,
    plugins: Iterable[str] = (),
    lsp: bool | dict[str, LspServer] = False,
) -> str:
    data = dict(existing)
    data[INSTRUCTIONS_KEY] = instruction_paths(resolved, source)
    data[MCP_KEY] = {server.name: mcp_entry(server) for server in servers}
    data[PLUGIN_KEY] = server_plugin_specs(plugins)
    data[LSP_KEY] = render_lsp(lsp)
    permission = dict(data.get(PERMISSION_KEY) or {})
    permission["lsp"] = "allow" if lsp else "deny"
    data[PERMISSION_KEY] = permission
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def render_tui_config(existing: dict[str, Any], plugins: Iterable[str] = ()) -> str:
    data = dict(existing)
    data.setdefault("$schema", TUI_SCHEMA)
    data[PLUGIN_KEY] = tui_plugin_specs(plugins)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
