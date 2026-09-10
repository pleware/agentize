"""Sync prefixed MCP keys into the user Cursor file.

Customize → MCPs in a multi-root ``.code-workspace`` often hides project
servers. The user file (``~/.cursor/mcp.json``) is the documented place that
window still lists. agentize owns only keys that start with ``agentize-``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .cascade import (
    absolutize_servers,
    child_dirs,
    identity_for_child,
    inherit_spec,
    load_child_config,
    load_mani,
    overlay_config,
)
from .config import Config, McpServer, Profile, identity_label
from .hosts.cursor import MCP_KEY, mcp_entry
from .mount import Plan, Write, _read_json

PREFIX = "agentize-"


def user_mcp_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def prefixed_name(name: str) -> str:
    return name if name.startswith(PREFIX) else f"{PREFIX}{name}"


def qualified_name(server_name: str, qualifier: str | None) -> str:
    """`postgres` → `agentize-postgres`, or `agentize-human.postgres`.

    The qualifier is the identity label, used when one user file carries every
    declared identity at once.
    """
    stem = f"{qualifier}.{server_name}" if qualifier else server_name
    return prefixed_name(stem)


def cursor_user_mcp_enabled(config: Config) -> bool:
    host = config.hosts.get("cursor")
    return host is not None and host.enabled and host.user_mcp


def _add_prefixed(
    wanted: dict[str, McpServer],
    root: Path,
    config: Config,
    identity: Profile,
    *,
    qualifier: str | None = None,
) -> None:
    if not identity.mcp:
        return
    absolute = absolutize_servers(config, root)
    for server in absolute.servers_for(identity):
        name = qualified_name(server.name, qualifier)
        wanted[name] = replace(server, name=name)


def collect_user_mcp_servers(
    root: Path,
    config: Config,
    identity: Profile,
    *,
    seen: set[Path] | None = None,
    qualifier: str | None = None,
) -> dict[str, McpServer]:
    """Union of this root plus every cascaded child that plants MCP.

    `qualifier` is the identity label: it distinguishes two identities' servers
    in one user file. Hermes leaves it unset — its profile directory is already
    per identity.
    """
    visited = seen if seen is not None else set()
    here = root.resolve()
    if here in visited:
        return {}
    visited.add(here)
    wanted: dict[str, McpServer] = {}
    _add_prefixed(wanted, root, config, identity, qualifier=qualifier)
    for child in child_dirs(root):
        child_config = load_child_config(child)
        merged = overlay_config(config, child_config) if child_config else config
        ident = identity_for_child(identity, child_config)
        # Child yaml may add servers. Paths resolve from each server's
        # declared_at (the yaml that defined it), so a binder walk does not
        # shift a child's --directory, and an inherit-only leaf does not
        # double the path (…/orchestrator/orchestrator).
        if inherit_spec(child).allows("mcp") and child_config is not None:
            _add_prefixed(wanted, child, merged, ident, qualifier=qualifier)
        if load_mani(child) is not None:
            wanted.update(
                collect_user_mcp_servers(child, merged, ident, seen=visited, qualifier=qualifier)
            )
    return wanted


def collect_all_user_mcp_servers(
    root: Path, config: Config, identities: tuple[Profile, ...]
) -> dict[str, McpServer]:
    """Every identity's servers in one map, keys qualified by identity label."""
    wanted: dict[str, McpServer] = {}
    for identity in identities:
        wanted.update(
            collect_user_mcp_servers(
                root, config, identity, qualifier=identity_label(identity)
            )
        )
    return wanted


def render_user_mcp(existing: dict, wanted: dict[str, McpServer]) -> dict:
    data = dict(existing)
    servers = dict(data.get(MCP_KEY) or {})
    if not isinstance(servers, dict):
        servers = {}
    originals = {server.name.removeprefix(PREFIX) for server in wanted.values()}
    for key in list(servers):
        stale_prefix = key.startswith(PREFIX) and key not in wanted
        unprefixed_dup = key in originals and not key.startswith(PREFIX)
        if stale_prefix or unprefixed_dup:
            del servers[key]
    for name, server in wanted.items():
        servers[name] = mcp_entry(server)
    data[MCP_KEY] = servers
    return data


def plan_user_mcp(
    wanted: dict[str, McpServer],
    *,
    path: Path | None = None,
) -> Plan:
    target = path or user_mcp_path()
    existing = _read_json(target)
    payload = render_user_mcp(existing, wanted)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return Plan(
        label=f"user mcp.json ({PREFIX}* {len(wanted)})",
        writes=(Write(target, text.encode("utf-8")),),
    )


def strip_user_mcp_prefix(*, path: Path | None = None) -> bool:
    """Remove ``agentize-*`` keys. Other user servers stay."""
    target = path or user_mcp_path()
    if not target.is_file():
        return False
    existing = _read_json(target)
    servers = existing.get(MCP_KEY)
    if not isinstance(servers, dict):
        return False
    kept = {name: spec for name, spec in servers.items() if not str(name).startswith(PREFIX)}
    if kept == servers:
        return False
    existing[MCP_KEY] = kept
    target.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True
