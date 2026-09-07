"""Render the resolved layers into each host's native files.

The filesystem sits at two thin edges: planning reads, `apply` writes. A plan is
a list of exact bytes per target, so every host shares one write-and-prune path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import skills
from .config import Config, Profile
from .errors import MountError
from .hosts import agents_md, cursor, opencode
from .resolve import ResolvedFile, resolve


@dataclass(frozen=True)
class Write:
    target: Path
    content: bytes


@dataclass(frozen=True)
class Plan:
    label: str
    writes: tuple[Write, ...] = ()
    deletes: tuple[Path, ...] = ()


def list_files(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file())
    )


def resolved_for(
    project_root: Path, config: Config, *, host: str | None, identity: Profile
) -> tuple[ResolvedFile, ...]:
    listing = list_files(project_root / config.source)
    return resolve(config, listing, host=host, identity=identity)


def plan_host_skills(
    project_root: Path,
    config: Config,
    *,
    host: str,
    identity: Profile,
    skills_dir: str,
    prefix: str,
) -> tuple[list[Write], list[Path], int]:
    """Copy each resolved skill directory whole, and drop what is no longer resolved."""
    source_root = project_root / config.source
    units = skills.skill_units(list_files(source_root))
    resolved = resolve(config, units, host=host, identity=identity)

    selected = identity.skills
    missing = skills.unknown_names(resolved, selected)
    if missing:
        raise MountError(
            f"profile {identity.name!r} asks for skills no layer provides: {', '.join(missing)}"
        )

    wanted = skills.plan_skills(resolved, prefix, selected)
    dst = project_root / skills_dir

    writes: list[Write] = []
    for item in wanted:
        origin = source_root / item.source
        for path in sorted(origin.rglob("*")):
            if path.is_file():
                target = dst / item.dir_name / path.relative_to(origin).as_posix()
                writes.append(Write(target, path.read_bytes()))

    keep = {item.target for item in writes}
    live = {item.dir_name for item in wanted}
    deletes: list[Path] = []
    if dst.is_dir():
        for child in sorted(dst.iterdir()):
            if not child.is_dir() or not child.name.startswith(prefix):
                continue
            for path in sorted(child.rglob("*")):
                if path.is_file() and (child.name not in live or path not in keep):
                    deletes.append(path)

    return writes, deletes, len(wanted)


def plan_cursor(
    project_root: Path,
    config: Config,
    identity: Profile,
    *,
    include: frozenset[str] | None = None,
) -> Plan:
    selected = include or frozenset({"rules", "skills", "mcp"})
    writes: list[Write] = []
    deletes: list[Path] = []
    wanted: list = []
    skill_count = 0
    servers = config.servers_for(identity) if "mcp" in selected else ()
    if servers:
        from .markers import bind_server_markers

        servers = tuple(bind_server_markers(server, project_root) for server in servers)
    host = config.hosts.get("cursor")
    prefix = (host.emit_prefix if host else "") or cursor.DEFAULT_PREFIX

    if "rules" in selected:
        resolved = resolved_for(project_root, config, host="cursor", identity=identity)
        wanted = list(cursor.plan_rules(resolved, prefix))
        source_root = project_root / config.source
        dst = project_root / cursor.RULES_DIR
        writes.extend(
            Write(dst / item.name, (source_root / item.source).read_bytes()) for item in wanted
        )
        existing = (
            sorted(item.name for item in dst.glob(f"*{cursor.RULE_SUFFIX}") if item.is_file())
            if dst.is_dir()
            else []
        )
        stale = cursor.stale_names(existing, [item.name for item in wanted], prefix)
        deletes.extend(dst / name for name in stale)

    if "mcp" in selected:
        mcp_target = project_root / cursor.MCP_FILE
        rendered = cursor.render_mcp(_read_json(mcp_target), servers)
        writes.append(Write(mcp_target, rendered.encode("utf-8")))

    if "skills" in selected:
        skill_writes, skill_deletes, skill_count = plan_host_skills(
            project_root,
            config,
            host="cursor",
            identity=identity,
            skills_dir=cursor.SKILLS_DIR,
            prefix=prefix,
        )
        writes.extend(skill_writes)
        deletes.extend(skill_deletes)

    label = ", ".join(
        (
            _count(len(wanted), "rule"),
            _count(skill_count, "skill"),
            _count(len(servers), "mcp server"),
        )
    )
    return Plan(label=f"cursor: {label}", writes=tuple(writes), deletes=tuple(deletes))


def plan_opencode(project_root: Path, config: Config, identity: Profile) -> Plan:
    resolved = resolved_for(project_root, config, host="opencode", identity=identity)
    servers = config.servers_for(identity)
    if servers:
        from .markers import bind_server_markers

        servers = tuple(bind_server_markers(server, project_root) for server in servers)
    target = project_root / opencode.CONFIG_FILE

    paths = opencode.instruction_paths(resolved, config.source)
    plugins = config.hosts["opencode"].plugins
    lsp = config.lsp_payload(identity)
    content = opencode.render_config(
        _read_json(target), resolved, servers, config.source, plugins, lsp
    )

    prefix = config.hosts["opencode"].emit_prefix or skills.DEFAULT_PREFIX
    skill_writes, skill_deletes, skill_count = plan_host_skills(
        project_root,
        config,
        host="opencode",
        identity=identity,
        skills_dir=opencode.SKILLS_DIR,
        prefix=prefix,
    )

    writes = [Write(target, content.encode("utf-8")), *skill_writes]
    tui_target = project_root / opencode.TUI_FILE
    tui_plugins = opencode.tui_plugin_specs(plugins)
    if tui_plugins or tui_target.is_file():
        writes.append(
            Write(
                tui_target,
                opencode.render_tui_config(_read_json(tui_target), plugins).encode("utf-8"),
            )
        )

    label = ", ".join(
        (
            _count(len(paths), "instruction"),
            _count(skill_count, "skill"),
            _count(len(servers), "mcp server"),
            _count(len(opencode.plugin_specs(plugins)), "plugin"),
            _lsp_label(lsp),
        )
    )
    return Plan(
        label=f"opencode: {label}",
        writes=tuple(writes),
        deletes=tuple(skill_deletes),
    )


def plan_agents_md(project_root: Path, config: Config, identity: Profile) -> Plan:
    resolved = resolved_for(project_root, config, host=None, identity=identity)
    target = project_root / agents_md.FILE
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    content = agents_md.merge(existing, agents_md.render_block(resolved, config.source))
    return Plan(
        label=f"{agents_md.FILE}: {_count(len(agents_md.rules(resolved)), 'rule')}",
        writes=(Write(target, content.encode("utf-8")),),
    )


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def _lsp_label(lsp: bool | dict) -> str:
    if lsp is True:
        return "lsp all"
    if not lsp:
        return "lsp off"
    return _count(len(lsp), "lsp server")


def changes(project_root: Path, plan: Plan) -> tuple[str, ...]:
    """What `apply` would do. Empty means the tree already matches the source."""
    out: list[str] = []
    for item in plan.writes:
        rel = item.target.relative_to(project_root).as_posix()
        if not item.target.is_file():
            out.append(f"create {rel}")
        elif item.target.read_bytes() != item.content:
            out.append(f"update {rel}")
    for target in plan.deletes:
        out.append(f"delete {target.relative_to(project_root).as_posix()}")
    return tuple(out)


def apply(project_root: Path, plan: Plan) -> tuple[str, ...]:
    """Write the plan. Unchanged files are left alone, so a second run touches nothing."""
    done = changes(project_root, plan)
    if not done:
        return ()

    for item in plan.writes:
        if item.target.is_file() and item.target.read_bytes() == item.content:
            continue
        item.target.parent.mkdir(parents=True, exist_ok=True)
        item.target.write_bytes(item.content)
    for target in plan.deletes:
        target.unlink(missing_ok=True)
    for target in plan.deletes:
        _prune_empty_dirs(target.parent, project_root)
    return done


def _prune_empty_dirs(directory: Path, stop: Path) -> None:
    """Remove directories emptied by a delete. A skill is a tree, not one file."""
    current = directory
    while current != stop and current.is_dir() and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MountError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise MountError(f"{path}: expected a JSON object")
    return data
