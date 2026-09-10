"""Render the resolved layers into each host's native files.

The filesystem sits at two thin edges: planning reads, `apply` writes. A plan is
a list of exact bytes per target, so every host shares one write-and-prune path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from . import skills
from .ancestry import cascade_rules
from .config import Config, LspServer, McpServer, Profile, identity_label
from .errors import MountError
from .hosts import agents_md, cursor, opencode
from .markers import bind_server_markers
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
    root: Path | None = None
    """If set, ``apply`` / ``changes`` resolve paths from here, not the project."""


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
    dest: Path | None = None,
) -> tuple[list[Write], list[Path], int]:
    """Copy each resolved skill directory whole, and drop what is no longer resolved."""
    return _plan_host_skills(
        project_root,
        config,
        host=host,
        identities=(identity,),
        skills_dir=skills_dir,
        prefix=prefix,
        dest=dest,
    )


def plan_host_skills_all(
    project_root: Path,
    config: Config,
    *,
    host: str,
    identities: tuple[Profile, ...],
    skills_dir: str,
    prefix: str,
    dest: Path | None = None,
) -> tuple[list[Write], list[Path], int]:
    """Every identity's skills at once, each directory carrying its label."""
    return _plan_host_skills(
        project_root,
        config,
        host=host,
        identities=tuple(identities),
        skills_dir=skills_dir,
        prefix=prefix,
        dest=dest,
    )


def _plan_host_skills(
    project_root: Path,
    config: Config,
    *,
    host: str,
    identities: tuple[Profile, ...],
    skills_dir: str,
    prefix: str,
    dest: Path | None = None,
) -> tuple[list[Write], list[Path], int]:
    """One pass over the skill directories, for one identity or all of them.

    Two identities resolving the same source are one entry; their labels keep
    them apart in the destination directory.
    """
    source_root = project_root / config.source
    disk_by_listing = skills.skill_resolve_map(skills.skill_units(list_files(source_root)))
    qualify = len(identities) > 1

    emitted: dict[str, skills.Emitted] = {}
    for identity in identities:
        resolved = resolve(config, disk_by_listing, host=host, identity=identity)
        selected = identity.skills
        missing = skills.unknown_names(resolved, selected)
        if missing:
            raise MountError(
                f"identity {identity.name!r} asks for skills no layer provides: "
                f"{', '.join(missing)}"
            )
        qualifier = identity_label(identity) if qualify else None
        for item in skills.plan_skills(resolved, prefix, selected, qualifier):
            clash = emitted.setdefault(item.dir_name, item)
            if clash.source != item.source:
                raise MountError(
                    f"{clash.source} and {item.source} would both be written as "
                    f"{item.dir_name}. Skill directory names must be unique within a host."
                )

    wanted = [emitted[name] for name in sorted(emitted)]
    dst = dest if dest is not None else project_root / skills_dir

    writes: list[Write] = []
    for item in wanted:
        origin = source_root / disk_by_listing.get(item.source, item.source)
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
    return _plan_cursor(project_root, config, (identity,), include=include)


def plan_cursor_all(
    project_root: Path,
    config: Config,
    identities: tuple[Profile, ...],
    *,
    include: frozenset[str] | None = None,
) -> Plan:
    """One plan holding every identity's rules, skills and MCP entries.

    Rules and MCP keys carry the identity label, so two identities do not
    overwrite each other and the prune set is a union, not a race.
    """
    return _plan_cursor(project_root, config, tuple(identities), include=include)


def _plan_cursor(
    project_root: Path,
    config: Config,
    identities: tuple[Profile, ...],
    *,
    include: frozenset[str] | None = None,
) -> Plan:
    selected = include or frozenset({"rules", "skills", "mcp"})
    qualify = len(identities) > 1
    writes: list[Write] = []
    deletes: list[Path] = []
    emitted_rules: dict[str, cursor.Emitted] = {}
    cascade_names: list[str] = []
    skill_count = 0
    servers: list[McpServer] = []
    host = config.hosts.get("cursor")
    prefix = (host.emit_prefix if host else "") or cursor.DEFAULT_PREFIX

    if "rules" in selected:
        source_root = project_root / config.source
        dst = project_root / cursor.RULES_DIR
        for identity in identities:
            resolved = resolved_for(project_root, config, host="cursor", identity=identity)
            qualifier = identity_label(identity) if qualify else None
            for item in cursor.plan_rules(resolved, prefix, qualifier):
                if item.name == cursor.GENERATED_RULE_NAME:
                    raise MountError(
                        f"a source rule would be written as {cursor.GENERATED_RULE_NAME}. "
                        "That name is reserved for the generated leave-alone rule."
                    )
                emitted_rules.setdefault(item.name, item)
        for rule in cascade_rules(project_root):
            name = cursor.emit_name(rule.key, prefix)
            if name == cursor.GENERATED_RULE_NAME:
                raise MountError(
                    f"a cascade rule would be written as {cursor.GENERATED_RULE_NAME}. "
                    "That name is reserved for the generated leave-alone rule."
                )
            if name in emitted_rules:
                continue  # the project's own rule wins over an inherited one
            cascade_names.append(name)
            writes.append(Write(dst / name, (rule.owner / rule.rel).read_bytes()))
        wanted = [emitted_rules[name] for name in sorted(emitted_rules)]
        writes.extend(
            Write(dst / item.name, (source_root / item.source).read_bytes()) for item in wanted
        )
        writes.append(
            Write(cursor.generated_rule_path(project_root), cursor.generated_rule_bytes())
        )
        wanted_names = [item.name for item in wanted] + cascade_names
        if cursor.GENERATED_RULE_NAME.startswith(prefix):
            wanted_names.append(cursor.GENERATED_RULE_NAME)
        existing = (
            sorted(item.name for item in dst.glob(f"*{cursor.RULE_SUFFIX}") if item.is_file())
            if dst.is_dir()
            else []
        )
        stale = cursor.stale_names(existing, wanted_names, prefix)
        deletes.extend(dst / name for name in stale)

    if "mcp" in selected:
        mcp_target = project_root / cursor.MCP_FILE
        for identity in identities:
            qualifier = identity_label(identity) if qualify else None
            for server in config.servers_for(identity):
                bound = bind_server_markers(server, project_root)
                if qualifier:
                    bound = replace(bound, name=f"{qualifier}.{bound.name}")
                servers.append(bound)
        rendered = cursor.render_mcp(_read_json(mcp_target), servers)
        writes.append(Write(mcp_target, rendered.encode("utf-8")))

    if "skills" in selected:
        skill_writes, skill_deletes, skill_count = _plan_host_skills(
            project_root,
            config,
            host="cursor",
            identities=identities,
            skills_dir=cursor.SKILLS_DIR,
            prefix=prefix,
        )
        writes.extend(skill_writes)
        deletes.extend(skill_deletes)

    rule_count = len(emitted_rules) + (1 if "rules" in selected else 0)
    label = ", ".join(
        (
            _count(rule_count, "rule"),
            _count(skill_count, "skill"),
            _count(len(servers), "mcp server"),
        )
    )
    if qualify:
        label = f"{_count(len(identities), 'identity', 'identities')}, {label}"
    return Plan(label=f"cursor: {label}", writes=tuple(writes), deletes=tuple(deletes))


def plan_opencode(project_root: Path, config: Config, identity: Profile) -> Plan:
    return _plan_opencode(project_root, config, (identity,))


def plan_opencode_all(
    project_root: Path, config: Config, identities: tuple[Profile, ...]
) -> Plan:
    """One `opencode.json` listing every identity's instructions, MCP and LSP."""
    return _plan_opencode(project_root, config, tuple(identities))


def _merge_lsp(
    payloads: tuple[bool | dict[str, LspServer], ...]
) -> bool | dict[str, LspServer]:
    """One `lsp` value for a file that carries every identity.

    `all` anywhere wins — it is the wider promise. Otherwise the named servers
    are unioned, first declaration first, and "everything off" stays `false`
    rather than an empty mapping.
    """
    if any(payload is True for payload in payloads):
        return True
    if not any(payloads):
        return False
    merged: dict[str, LspServer] = {}
    for payload in payloads:
        if isinstance(payload, dict):
            for name, server in payload.items():
                merged.setdefault(name, server)
    return merged


def _plan_opencode(
    project_root: Path, config: Config, identities: tuple[Profile, ...]
) -> Plan:
    qualify = len(identities) > 1
    resolved_by_path: dict[str, ResolvedFile] = {}
    servers: list[McpServer] = []
    payloads: list[bool | dict[str, LspServer]] = []
    for identity in identities:
        resolved = resolved_for(project_root, config, host="opencode", identity=identity)
        for item in resolved:
            resolved_by_path.setdefault(item.path, item)
        qualifier = identity_label(identity) if qualify else None
        for server in config.servers_for(identity):
            bound = bind_server_markers(server, project_root)
            if qualifier:
                bound = replace(bound, name=f"{qualifier}.{bound.name}")
            servers.append(bound)
        payloads.append(config.lsp_payload(identity))

    resolved_all = tuple(resolved_by_path.values())
    target = project_root / opencode.CONFIG_FILE

    paths = opencode.instruction_paths(resolved_all, config.source)
    plugins = config.hosts["opencode"].plugins
    lsp = _merge_lsp(tuple(payloads))
    content = opencode.render_config(
        _read_json(target), resolved_all, servers, config.source, plugins, lsp
    )

    prefix = config.hosts["opencode"].emit_prefix or skills.DEFAULT_PREFIX
    skill_writes, skill_deletes, skill_count = _plan_host_skills(
        project_root,
        config,
        host="opencode",
        identities=identities,
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
    if qualify:
        label = f"{_count(len(identities), 'identity', 'identities')}, {label}"
    return Plan(
        label=f"opencode: {label}",
        writes=tuple(writes),
        deletes=tuple(skill_deletes),
    )


def plan_agents_md(project_root: Path, config: Config, identity: Profile) -> Plan:
    return _plan_agents_md(project_root, config, (identity,))


def plan_agents_md_all(
    project_root: Path, config: Config, identities: tuple[Profile, ...]
) -> Plan:
    """The host-neutral index, with one section per identity."""
    return _plan_agents_md(project_root, config, tuple(identities))


def _plan_agents_md(
    project_root: Path, config: Config, identities: tuple[Profile, ...]
) -> Plan:
    qualify = len(identities) > 1
    groups = tuple(
        (
            agents_md.identity_heading(identity) if qualify else "",
            resolved_for(project_root, config, host=None, identity=identity),
        )
        for identity in identities
    )
    target = project_root / agents_md.FILE
    existing = target.read_text(encoding="utf-8") if target.is_file() else ""
    block = (
        agents_md.render_block_all(groups, config.source)
        if qualify
        else agents_md.render_block(groups[0][1], config.source)
    )
    content = agents_md.merge(existing, block)
    rule_count = sum(len(agents_md.rules(items)) for _heading, items in groups)
    if qualify:
        label = (
            f"{agents_md.FILE}: {_count(len(identities), 'identity', 'identities')}, "
            f"{_count(rule_count, 'rule')}"
        )
    else:
        label = f"{agents_md.FILE}: {_count(rule_count, 'rule')}"
    return Plan(label=label, writes=(Write(target, content.encode("utf-8")),))


def _count(number: int, noun: str, plural: str | None = None) -> str:
    if number == 1:
        return f"{number} {noun}"
    return f"{number} {plural or f'{noun}s'}"


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
