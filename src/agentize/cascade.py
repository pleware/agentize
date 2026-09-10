"""Walk `mani.yaml` and plant parent MCP into existing children.

`mount` at a registry always cascades. A child without `agentize.yaml` still
inherits (opt-out is `inherit: []` / `inherit: false`). Cascade writes
`.cursor/mcp.json`, `.cursor/rules/auto.do-not-edit.mdc`, and
`.agentize/parents.yaml` — never `AGENTS.md`.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import yaml

from .ancestry import ObservedParent, cascade_rules, observed_parents
from .config import CONFIG_NAME, Config, InheritSpec, McpServer, Profile, load_config
from .errors import AgentizeError
from .hosts import cursor
from .mani import child_dirs, load_mani
from .markers import bind_markers
from .mount import Plan, Write, apply, changes, plan_cursor_all
from .store_tree import DIR_NAME, ensure_data_dir

PARENTS_FILE = f"{DIR_NAME}/parents.yaml"
DIRECTORY_FLAGS = frozenset({"--directory", "-C", "--project"})


class CascadeError(AgentizeError):
    """A child policy could not be merged onto the parent."""


def posix_rel(target: Path, start: Path) -> str:
    return Path(os.path.relpath(target.resolve(), start.resolve())).as_posix()


def rebase_relpath(value: str, from_root: Path, to_root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return value
    return posix_rel((from_root / path).resolve(), to_root)


def rebase_command(command: tuple[str, ...], from_root: Path, to_root: Path) -> tuple[str, ...]:
    out: list[str] = []
    rebase_next = False
    for arg in command:
        if rebase_next:
            out.append(rebase_relpath(arg, from_root, to_root))
            rebase_next = False
            continue
        if arg in DIRECTORY_FLAGS:
            rebase_next = True
        out.append(arg)
    return tuple(out)


def absolutize_relpath(value: str, from_root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((from_root / path).resolve())


def absolutize_command(command: tuple[str, ...], from_root: Path) -> tuple[str, ...]:
    out: list[str] = []
    rebase_next = False
    for arg in command:
        if rebase_next:
            out.append(absolutize_relpath(arg, from_root))
            rebase_next = False
            continue
        if arg in DIRECTORY_FLAGS:
            rebase_next = True
        out.append(arg)
    return tuple(out)


def command_root(server: McpServer, fallback: Path) -> Path:
    """Yaml directory that owns this server, else the cascade parent."""
    return server.declared_at if server.declared_at is not None else fallback


def absolutize_servers(config: Config, from_root: Path) -> Config:
    servers = {
        name: replace(
            server,
            command=absolutize_command(server.command, command_root(server, from_root)),
        )
        for name, server in config.servers.items()
    }
    return bind_markers(replace(config, servers=servers), from_root)


def rebase_servers(config: Config, from_root: Path, to_root: Path) -> Config:
    servers = {
        name: replace(
            server,
            command=rebase_command(
                server.command, command_root(server, from_root), to_root
            ),
        )
        for name, server in config.servers.items()
    }
    return bind_markers(replace(config, servers=servers), from_root)


def load_child_config(root: Path) -> Config | None:
    path = root / CONFIG_NAME
    if not path.is_file():
        return None
    return load_config(path)


def inherit_spec(root: Path) -> InheritSpec:
    child = load_child_config(root)
    return child.inherit if child is not None else InheritSpec()


def overlay_config(parent: Config, child: Config) -> Config:
    return replace(
        parent,
        hosts={**parent.hosts, **child.hosts},
        profiles={**parent.profiles, **child.profiles},
        servers={**parent.servers, **child.servers},
        agents={**parent.agents, **child.agents},
        lsp_servers={**parent.lsp_servers, **child.lsp_servers},
        inherit=child.inherit,
    )


def identity_for_child(parent_identity: Profile, child: Config | None) -> Profile:
    if child is None:
        return parent_identity
    if parent_identity.name in child.profiles:
        return child.profiles[parent_identity.name]
    if parent_identity.name in child.agents:
        return child.resolve_agent(parent_identity.name)
    return parent_identity


def parents_yaml(child: Path, parents: tuple[ObservedParent, ...]) -> str:
    payload = {
        "parents": [
            {"rel": posix_rel(item.root, child), "kind": item.kind} for item in parents
        ]
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)


def plan_parents_file(child: Path) -> Plan:
    text = parents_yaml(child, observed_parents(child))
    target = child / PARENTS_FILE
    return Plan(
        label="parents.yaml",
        writes=(Write(target, text.encode("utf-8")),),
    )


def plan_generated_rule(child: Path) -> Plan:
    return Plan(
        label="cursor: generated rule",
        writes=(Write(cursor.generated_rule_path(child), cursor.generated_rule_bytes()),),
    )


def plan_cascade_rules(child: Path, *, config: Config | None = None) -> Plan:
    """Shared `cascade/` rules into the child's `.cursor/rules/`.

    The set comes from the child and every observed ancestor (nearest wins), so
    the child's own mount and a parent's cascade plant the same bytes under the
    same names.
    """
    cfg = config if config is not None else load_child_config(child)
    host = cfg.hosts.get("cursor") if cfg is not None else None
    prefix = (host.emit_prefix if host else "") or cursor.DEFAULT_PREFIX
    dst = child / cursor.RULES_DIR
    writes: list[Write] = []
    for rule in cascade_rules(child):
        name = cursor.emit_name(rule.key, prefix)
        if name == cursor.GENERATED_RULE_NAME:
            raise CascadeError(
                f"a cascade rule would be written as {cursor.GENERATED_RULE_NAME}; "
                "that name is reserved for the generated leave-alone rule."
            )
        writes.append(Write(dst / name, (rule.owner / rule.rel).read_bytes()))
    return Plan(label="cursor: cascade rules", writes=tuple(writes))


def plan_inherited_mcp(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identity: Profile,
) -> Plan:
    return _plan_inherited_mcp(parent_root, child, parent_config, (parent_identity,))


def plan_inherited_mcp_all(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
) -> Plan:
    """Inherited MCP for every identity, in one plan against the child's file."""
    return _plan_inherited_mcp(parent_root, child, parent_config, tuple(parent_identities))


def _plan_inherited_mcp(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
) -> Plan:
    child_config = load_child_config(child)
    merged = overlay_config(parent_config, child_config) if child_config else parent_config
    identities = tuple(identity_for_child(item, child_config) for item in parent_identities)
    for identity in identities:
        missing = [name for name in identity.mcp if name not in merged.servers]
        if missing:
            raise CascadeError(
                f"{child}: profile {identity.name!r} references unknown server "
                f"{missing[0]!r} after cascade merge"
            )
    rebased = rebase_servers(merged, parent_root, child)
    return plan_cursor_all(child, rebased, identities, include=frozenset({"mcp"}))


def apply_or_check(root: Path, plan: Plan, *, check: bool) -> tuple[str, ...]:
    return changes(root, plan) if check else apply(root, plan)


def plant_child(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identity: Profile,
    *,
    check: bool,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    return _plant_child(parent_root, child, parent_config, (parent_identity,), check=check)


def plant_child_all(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
    *,
    check: bool,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    """Plant inherited MCP, the leave-alone rule and observed parents, for all."""
    return _plant_child(parent_root, child, parent_config, tuple(parent_identities), check=check)


def _plant_child(
    parent_root: Path,
    child: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
    *,
    check: bool,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    """Plant inherited MCP, the leave-alone rule, and observed parents.

    Skip MCP when inherit refuses. The generated Cursor rule still lands so
    agents do not patch `auto.*` files in a child that has none of its own.
    `check` reports without writing, which includes not creating `.agentize/`.
    """
    results: list[tuple[str, Plan, tuple[str, ...]]] = []
    spec = inherit_spec(child)
    label = posix_rel(child, parent_root)
    child_config = load_child_config(child)
    identities = tuple(identity_for_child(item, child_config) for item in parent_identities)
    if spec.allows("mcp") and any(identity.mcp for identity in identities):
        mcp_plan = _plan_inherited_mcp(parent_root, child, parent_config, parent_identities)
        results.append((label, mcp_plan, apply_or_check(child, mcp_plan, check=check)))
    cascade_plan = plan_cascade_rules(child, config=child_config)
    results.append((label, cascade_plan, apply_or_check(child, cascade_plan, check=check)))
    if not check:
        ensure_data_dir(child)
    rule_plan = plan_generated_rule(child)
    results.append((label, rule_plan, apply_or_check(child, rule_plan, check=check)))
    parents_plan = plan_parents_file(child)
    results.append((label, parents_plan, apply_or_check(child, parents_plan, check=check)))
    return results


def cascade(
    parent_root: Path,
    parent_config: Config,
    parent_identity: Profile,
    *,
    check: bool,
    seen: set[Path] | None = None,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    return _cascade(parent_root, parent_config, (parent_identity,), check=check, seen=seen)


def cascade_all(
    parent_root: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
    *,
    check: bool,
    seen: set[Path] | None = None,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    """Walk every child for every declared identity."""
    return _cascade(
        parent_root, parent_config, tuple(parent_identities), check=check, seen=seen
    )


def _cascade(
    parent_root: Path,
    parent_config: Config,
    parent_identities: tuple[Profile, ...],
    *,
    check: bool,
    seen: set[Path] | None = None,
) -> list[tuple[str, Plan, tuple[str, ...]]]:
    """Rebuild every existing child of this registry, then their registries."""
    visited = seen if seen is not None else set()
    here = parent_root.resolve()
    if here in visited:
        return []
    visited.add(here)
    out: list[tuple[str, Plan, tuple[str, ...]]] = []
    for child in child_dirs(parent_root):
        out.extend(
            _plant_child(parent_root, child, parent_config, parent_identities, check=check)
        )
        child_config = load_child_config(child)
        next_config = overlay_config(parent_config, child_config) if child_config else parent_config
        next_identities = tuple(
            identity_for_child(item, child_config) for item in parent_identities
        )
        if load_mani(child) is not None:
            out.extend(
                _cascade(child, next_config, next_identities, check=check, seen=visited)
            )
    return out
