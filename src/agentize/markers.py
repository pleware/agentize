"""Resolve `${marker:rel/path}` in planted MCP env.

The walk is the nested registry (binder → workspace → product), not a
product folder name. Unresolved markers are dropped — runtime discovery
can still find the tree.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .config import Config, McpServer
from .mani import discover_up_and_down

MARKER_REF = re.compile(r"^\$\{marker:(.+)\}$")


def resolve_marker_value(value: str, start: Path) -> str | None:
    match = MARKER_REF.match(value.strip())
    if match is None:
        return value
    rel = match.group(1).strip()
    if not rel:
        return None
    found = discover_up_and_down(start, rel)
    return str(found) if found is not None else None


def bind_server_markers(server: McpServer, start: Path) -> McpServer:
    if not server.env:
        return server
    search = server.declared_at if server.declared_at is not None else start
    env: dict[str, str] = {}
    for key, value in server.env.items():
        resolved = resolve_marker_value(value, search)
        if resolved is not None:
            env[key] = resolved
    return replace(server, env=env)


def bind_markers(config: Config, start: Path) -> Config:
    servers = {
        name: bind_server_markers(server, start) for name, server in config.servers.items()
    }
    return replace(config, servers=servers)
