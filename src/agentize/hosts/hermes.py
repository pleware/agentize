"""Render MCP into a Hermes profile home.

Hermes has no project ``mcp.json``. It reads ``mcp_servers`` from
``$HERMES_HOME/config.yaml``. agentize therefore writes a dedicated profile
directory and sets ``HERMES_HOME`` on launch.

Every identity lands under ``<hermes-root>/profiles/agentize-<label>/``.
The root is the first existing directory among the platform-native home
(``%LOCALAPPDATA%/hermes`` on Windows) and ``~/.hermes``. ``isolate_data``
does not move a Hermes profile into the project — Desktop must see the
bot next to the human. The default agent slug is labelled ``agent``, so
``agents.default`` becomes ``agentize-agent``.

``mount`` plants every declared profile and agent slug, not only the
current identity. Only keys prefixed ``agentize-`` are owned. Catalog
entries and hand-edited servers stay. Skills go into that same profile
``skills/`` tree under the host ``emit_prefix`` (default ``auto.``), so
bundled Hermes skills are not pruned. ``fetch`` does not download Hermes
— it locates the machine install.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from .. import skills
from ..config import Config, McpServer, Profile, identity_label
from ..errors import AgentizeError, MountError
from ..mount import Plan, Write, plan_host_skills
from ..user_mcp import PREFIX, collect_user_mcp_servers

CONFIG_FILE = "config.yaml"
MCP_KEY = "mcp_servers"
PROFILES_DIR = "profiles"
SKILLS_DIR = "skills"


def _user_home() -> Path:
    return Path.home()


def hermes_root_candidates() -> tuple[Path, ...]:
    """Native Hermes home first, then ``~/.hermes``.

    Official Windows Desktop and the installer use
    ``%LOCALAPPDATA%/hermes``. POSIX and WSL use ``~/.hermes``. A machine
    may have both; ``user_hermes_root`` picks the first that exists.
    """
    found: list[Path] = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else _user_home() / "AppData" / "Local"
        found.append(base / "hermes")
    posix = _user_home() / ".hermes"
    if not found or posix != found[0]:
        found.append(posix)
    return tuple(found)


def existing_hermes_roots() -> tuple[Path, ...]:
    return tuple(path for path in hermes_root_candidates() if path.is_dir())


def user_hermes_root() -> Path:
    candidates = hermes_root_candidates()
    for path in candidates:
        if path.is_dir():
            return path
    return candidates[0]


def hermes_enabled(config: Config) -> bool:
    host = config.hosts.get("hermes")
    return host is not None and host.enabled


def profile_dir_name(identity: Profile) -> str:
    return f"{PREFIX}{identity_label(identity)}"


def profile_home(project_root: Path, identity: Profile) -> Path:
    """Desktop profile directory. ``project_root`` is unused (kept for callers)."""
    return user_hermes_root() / PROFILES_DIR / profile_dir_name(identity)


def hermes_identities(config: Config) -> tuple[Profile, ...]:
    """Every profile and agent slug, unique by Desktop directory name.

    The same set `mount --profile-all` renders for the other hosts.
    """
    return config.all_identities()


def apply_root(project_root: Path, dest: Path) -> Path:
    """Ancestor used for ``create``/``update`` lines."""
    try:
        dest.resolve().relative_to(project_root.resolve())
    except ValueError:
        return dest.parent.parent.parent
    return project_root


def mcp_entry(server: McpServer) -> dict[str, Any]:
    if server.is_remote:
        entry: dict[str, Any] = {"url": server.url}
        if server.headers:
            entry["headers"] = dict(server.headers)
        return entry

    entry = {"command": server.command[0]}
    if len(server.command) > 1:
        entry["args"] = list(server.command[1:])
    if server.env:
        entry["env"] = dict(server.env)
    return entry


def render_mcp(existing: dict[str, Any], wanted: dict[str, McpServer]) -> str:
    data = dict(existing)
    servers = dict(data.get(MCP_KEY) or {})
    if not isinstance(servers, dict):
        servers = {}
    for key in list(servers):
        if str(key).startswith(PREFIX) and key not in wanted:
            del servers[key]
    for name, server in wanted.items():
        servers[name] = mcp_entry(server)
    data[MCP_KEY] = servers
    return yaml.safe_dump(
        data,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MountError(f"{path}: not valid YAML ({exc})") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MountError(f"{path}: expected a YAML mapping")
    return data


def skills_prefix(config: Config) -> str:
    host = config.hosts.get("hermes")
    return (host.emit_prefix if host else "") or skills.DEFAULT_PREFIX


def plan_mcp(project_root: Path, config: Config, identity: Profile) -> Plan:
    wanted = collect_user_mcp_servers(project_root, config, identity)
    dest = profile_home(project_root, identity)
    target = dest / CONFIG_FILE
    rendered = render_mcp(read_yaml(target), wanted)
    noun = "mcp server" if len(wanted) == 1 else "mcp servers"
    return Plan(
        label=f"hermes: {len(wanted)} {noun}",
        writes=(Write(target, rendered.encode("utf-8")),),
        root=apply_root(project_root, dest),
    )


def plan(project_root: Path, config: Config, identity: Profile) -> Plan:
    """MCP servers and prefixed project skills for one Desktop identity."""
    mcp = plan_mcp(project_root, config, identity)
    dest = profile_home(project_root, identity) / SKILLS_DIR
    skill_writes, skill_deletes, skill_count = plan_host_skills(
        project_root,
        config,
        host="hermes",
        identity=identity,
        skills_dir=SKILLS_DIR,
        prefix=skills_prefix(config),
        dest=dest,
    )
    noun = "skill" if skill_count == 1 else "skills"
    return Plan(
        label=f"{mcp.label}, {skill_count} {noun}",
        writes=(*mcp.writes, *skill_writes),
        deletes=(*mcp.deletes, *skill_deletes),
        root=mcp.root,
    )


def locate_binary() -> Path:
    """The machine install — Hermes is not unpacked into ``.agentize/hosts``."""
    found = shutil.which("hermes")
    if found:
        return Path(found)
    for root in hermes_root_candidates():
        for path in (
            root / "hermes-agent" / "venv" / "bin" / "hermes",
            root / "hermes-agent" / "venv" / "Scripts" / "hermes.exe",
            root / "bin" / "hermes",
            root / "bin" / "hermes.exe",
        ):
            if path.is_file():
                return path
    raise AgentizeError(
        "hermes is not on PATH and no install was found under "
        "%LOCALAPPDATA%\\hermes or ~/.hermes. "
        "Install Hermes with its own installer, then retry"
    )


def strip_agentize_profiles(*, root: Path | None = None) -> tuple[Path, ...]:
    """Remove ``agentize-*`` profile directories. Other Hermes profiles stay."""
    homes = (root,) if root is not None else existing_hermes_roots()
    removed: list[Path] = []
    for home in homes:
        base = home / PROFILES_DIR
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name.startswith(PREFIX):
                try:
                    shutil.rmtree(child)
                except OSError:
                    continue
                removed.append(child)
    return tuple(removed)


def drop_stale_named_profiles(identity: Profile, keep: Path) -> tuple[Path, ...]:
    """Remove the same ``agentize-<name>`` dir from every other Hermes root."""
    name = profile_dir_name(identity)
    keep_key = keep.resolve()
    removed: list[Path] = []
    for home in existing_hermes_roots():
        stale = home / PROFILES_DIR / name
        if stale.resolve() == keep_key or not stale.is_dir():
            continue
        try:
            shutil.rmtree(stale)
        except OSError:
            continue
        removed.append(stale)
    return tuple(removed)


def servers_from(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    servers = data.get(MCP_KEY) or {}
    return servers if isinstance(servers, dict) else {}
