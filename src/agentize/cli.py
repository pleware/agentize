"""agentize command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .cascade import cascade, find_inherit_root, plant_child
from .cleanup import apply_cleanup, describe, plan_cleanup
from .config import CONFIG_NAME, ConfigError, Profile, load_config
from .errors import AgentizeError
from .ignite import ensure_toolchain
from .install import fetch_host
from .launch import executable, global_executable, launch_env, prepare, select_host, spawn
from .markers import bind_server_markers
from .hosts import hermes
from .mount import (
    Plan,
    apply,
    changes,
    plan_agents_md,
    plan_cursor,
    plan_opencode,
)
from .session import LastRun, load_last, remember
from .store_tree import config_is_ignored, config_path, ensure_data_dir
from .user_mcp import (
    collect_user_mcp_servers,
    cursor_user_mcp_enabled,
    plan_user_mcp,
    strip_user_mcp_prefix,
    user_mcp_path,
)
from .wrapper import write_wrappers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentize",
        description="One project config. Every agent host.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "-C",
        "--directory",
        type=Path,
        default=None,
        metavar="PATH",
        help="project root (default: current directory)",
    )
    parser.add_argument(
        "--host",
        metavar="NAME",
        help="host for run or fetch (default: the remembered or default host)",
    )
    parser.add_argument(
        "--profile",
        metavar="NAME",
        help="profile for run or mount (default: the remembered or default profile)",
    )
    parser.add_argument(
        "--agent",
        metavar="SLUG",
        help="agent slug for run or mount (agents.default plus this overlay)",
    )
    parser.add_argument(
        "--global",
        dest="use_global",
        action="store_true",
        help="use the host on PATH instead of the project's isolated copy",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="remove .agentize/ and planted launchers (same as the cleanup command)",
    )
    parser.add_argument(
        "--home",
        dest="cleanup_home",
        action="store_true",
        help="with cleanup, also remove ~/.agentize/",
    )
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("init", help=f"report where {CONFIG_NAME} goes and prepare data")

    cleanup = subcommands.add_parser(
        "cleanup",
        help="remove .agentize/ and planted launchers; leave agentize.yaml",
    )
    cleanup.add_argument(
        "--check",
        action="store_true",
        help="report what would be removed and exit non-zero, without deleting",
    )
    cleanup.add_argument(
        "--home",
        dest="cleanup_home",
        action="store_true",
        help="also remove ~/.agentize/",
    )

    mount = subcommands.add_parser("mount", help="render rules for each enabled host")
    mount.add_argument("--profile", metavar="NAME", help="profile to render (default: from config)")
    mount.add_argument("--agent", metavar="SLUG", help="agent slug to render")
    mount.add_argument(
        "--check",
        action="store_true",
        help="report what would change and exit non-zero, without writing",
    )

    run = subcommands.add_parser("run", help="launch a host with the profile applied (default)")
    run.add_argument("--profile", metavar="NAME", help="profile to apply (default: from config)")
    run.add_argument("--agent", metavar="SLUG", help="agent slug to apply")
    run.add_argument("--host", metavar="NAME", help="host to launch (default: the enabled one)")
    run.add_argument(
        "--global",
        dest="use_global",
        action="store_true",
        help="use the host on PATH instead of the project's isolated copy",
    )
    run.add_argument(
        "extra",
        nargs=argparse.REMAINDER,
        help="arguments passed through to the host (put them after --)",
    )

    fetch = subcommands.add_parser("fetch", help="install hosts into .agentize/hosts/")
    fetch.add_argument(
        "--host", metavar="NAME", help="fetch one host (default: every enabled host)"
    )
    return parser


def cmd_init(root: Path) -> int:
    directory = ensure_data_dir(root)
    config = config_path(root)
    print(f"agentize: policy {config}")
    print(f"agentize: data   {directory}")

    for path in write_wrappers(root):
        print(f"agentize: launcher {path.name}")

    if config_is_ignored(root):
        print(
            f"agentize: {CONFIG_NAME} is ignored by .gitignore, so it can never be\n"
            f"agentize: committed. Whitelist it with: !/{CONFIG_NAME}",
            file=sys.stderr,
        )
        return 1

    if not config.is_file():
        print(f"agentize: write {config} to continue")
    return 0


def cmd_cleanup(root: Path, *, check: bool, home: bool) -> int:
    plan = plan_cleanup(root, home=home)
    lines = list(describe(plan, root))
    if home:
        lines.append("remove agentize-* from ~/.cursor/mcp.json")
        lines.append("remove agentize-* from Hermes profiles")
    if not lines:
        print("agentize: nothing to clean")
        return 0
    for line in lines:
        print(f"agentize: {line}")
    if check:
        return 1
    apply_cleanup(plan)
    if home:
        strip_user_mcp_prefix()
        stripped = hermes.strip_agentize_profiles()
        for path in stripped:
            print(f"agentize: remove {path}")
    return 0


PLAN_BUILDERS = {"cursor": plan_cursor, "opencode": plan_opencode}
# Hermes writes a profile home from `_emit_hermes`, not a project file.
HOME_HOSTS = frozenset({"hermes"})


def mount_plans(root: Path, config, identity: Profile) -> list[Plan]:
    plans = [plan_agents_md(root, config, identity)]
    for host in config.enabled_hosts():
        if host.name in HOME_HOSTS:
            continue
        builder = PLAN_BUILDERS.get(host.name)
        if builder is None:
            print(f"agentize: {host.name}: no renderer in this build, skipped", file=sys.stderr)
            continue
        plans.append(builder(root, config, identity))
    return plans


def _select_identity(config, *, profile_name, agent_name, last: LastRun):
    return config.select_driver(
        profile_name,
        agent_name,
        last_profile=last.profile,
        last_agent=last.agent,
    )


def _memory_for(identity: Profile) -> tuple[str | None, str | None]:
    if identity.origin == "agent":
        return None, identity.name
    return identity.name, None


def _print_plan(root: Path, plan: Plan, *, check: bool, prefix: str = "") -> int:
    base = plan.root or root
    lines = changes(base, plan) if check else apply(base, plan)
    for line in lines:
        print(f"  {line}")
    print(f"agentize: {prefix}{plan.label}")
    return len(lines) if check else 0


def _emit_cascade(
    rows: list,
    *,
    identity: Profile,
    check: bool,
) -> int:
    pending = 0
    for label, plan, lines in rows:
        for line in lines:
            print(f"  {line}")
        pending += len(lines) if check else 0
        print(f"agentize: cascade {label} [{identity.name}] {plan.label}")
    return pending


def cmd_mount(
    root: Path,
    *,
    profile_name: str | None,
    agent_name: str | None,
    check: bool,
) -> int:
    policy = config_path(root)
    pending = 0
    last = load_last(root)

    if policy.is_file():
        config = load_config(policy)
        identity = _select_identity(
            config, profile_name=profile_name, agent_name=agent_name, last=last
        )
        for plan in mount_plans(root, config, identity):
            pending += _print_plan(root, plan, check=check, prefix=f"[{identity.name}] ")
        pending += _emit_cascade(
            cascade(root, config, identity, check=check),
            identity=identity,
            check=check,
        )
        pending += _emit_user_mcp(root, config, identity, check=check)
        pending += _emit_hermes(root, config, identity, check=check)
    else:
        parent = find_inherit_root(root)
        if parent is None:
            raise ConfigError(f"no configuration at {policy}")
        config = load_config(config_path(parent))
        identity = _select_identity(
            config, profile_name=profile_name, agent_name=agent_name, last=last
        )
        pending += _emit_cascade(
            plant_child(parent, root, config, identity, check=check),
            identity=identity,
            check=check,
        )
        pending += _emit_user_mcp(parent, config, identity, check=check)
        pending += _emit_hermes(parent, config, identity, check=check)

    if check and pending:
        print(f"agentize: {pending} file(s) out of date — run: agentize mount", file=sys.stderr)
        return 1
    return 0


def _emit_user_mcp(root: Path, config, identity: Profile, *, check: bool) -> int:
    if not cursor_user_mcp_enabled(config):
        return 0
    wanted = collect_user_mcp_servers(root, config, identity)
    plan = plan_user_mcp(wanted)
    return _print_plan(user_mcp_path().parent.parent, plan, check=check, prefix="[human] ")


def _emit_hermes(root: Path, config, identity: Profile, *, check: bool) -> int:
    if not hermes.hermes_enabled(config):
        return 0
    plan = hermes.plan_mcp(root, config, identity)
    code = _print_plan(root, plan, check=check, prefix=f"[{identity.name}] ")
    if not check:
        keep = hermes.profile_home(root, identity)
        for path in hermes.drop_stale_named_profiles(identity, keep):
            print(f"  remove stale {path}")
    return code


def _mount_for_run(root: Path, config, identity: Profile) -> None:
    for plan in mount_plans(root, config, identity):
        for line in apply(root, plan):
            print(f"  {line}", file=sys.stderr)
    for _label, _plan, lines in cascade(root, config, identity, check=False):
        for line in lines:
            print(f"  {line}", file=sys.stderr)
    if cursor_user_mcp_enabled(config):
        wanted = collect_user_mcp_servers(root, config, identity)
        for line in apply(user_mcp_path().parent.parent, plan_user_mcp(wanted)):
            print(f"  {line}", file=sys.stderr)
    if hermes.hermes_enabled(config):
        plan = hermes.plan_mcp(root, config, identity)
        for line in apply(plan.root or root, plan):
            print(f"  {line}", file=sys.stderr)
        keep = hermes.profile_home(root, identity)
        for path in hermes.drop_stale_named_profiles(identity, keep):
            print(f"  remove stale {path}", file=sys.stderr)


def cmd_run(
    root: Path,
    *,
    profile_name: str | None,
    agent_name: str | None,
    host_name: str | None,
    use_global: bool,
    extra: list[str],
) -> int:
    last = load_last(root)
    chosen_global = use_global if use_global or host_name is not None else last.use_global

    policy = config_path(root)
    if not policy.is_file():
        return _run_without_policy(
            root, host_name=host_name or last.host, extra=extra
        )

    config = load_config(policy)
    identity = _select_identity(
        config, profile_name=profile_name, agent_name=agent_name, last=last
    )
    host = select_host(config, host_name, last.host)
    use_global = chosen_global
    profile_mem, agent_mem = _memory_for(identity)

    remember(
        root,
        LastRun(
            host=host.name,
            profile=profile_mem,
            agent=agent_mem,
            use_global=use_global,
        ),
    )
    _mount_for_run(root, config, identity)
    prepare(root, identity, host.name)
    servers = tuple(
        bind_server_markers(server, root) for server in config.servers_for(identity)
    )
    env = launch_env(dict(os.environ), root, identity, host.name, servers=servers)
    if identity.origin == "agent":
        tools = ", ".join(identity.needs) or "mise.toml"
        print(f"agentize: ignite ensure ({tools})", file=sys.stderr)
        env.update(ensure_toolchain(root, identity.needs, env))
    argv = [executable(root, host, use_global=use_global), *extra]

    source = "PATH" if use_global else "isolated"
    print(f"agentize: {host.name} [{identity.name}] ({source})", file=sys.stderr)
    return spawn(root, argv, env)


def _run_without_policy(root: Path, *, host_name: str | None, extra: list[str]) -> int:
    if not host_name:
        raise AgentizeError(
            f"no {CONFIG_NAME} here and no last host to repeat. "
            f"Pass --host or write {CONFIG_NAME}."
        )
    remember(root, LastRun(host=host_name, use_global=True))
    argv = [global_executable(host_name), *extra]
    print(f"agentize: {host_name} (PATH, no {CONFIG_NAME})", file=sys.stderr)
    return spawn(root, argv, dict(os.environ))


def cmd_fetch(root: Path, *, host_name: str | None) -> int:
    config = load_config(config_path(root))
    hosts = [select_host(config, host_name)] if host_name else list(config.enabled_hosts())
    if not hosts:
        print("agentize: no enabled host to fetch", file=sys.stderr)
        return 1
    for host in hosts:
        if host.name == "hermes":
            try:
                binary = hermes.locate_binary()
            except AgentizeError:
                if host_name is not None:
                    raise
                print(
                    "agentize: hermes: no download recipe; install Hermes itself",
                    file=sys.stderr,
                )
                continue
            print(f"agentize: hermes → {binary} (external install)")
            continue
        binary = fetch_host(root, host)
        print(f"agentize: fetched {host.name} {host.pin} → {binary}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.directory or Path.cwd()).resolve()

    try:
        if args.cleanup or args.command == "cleanup":
            return cmd_cleanup(
                root,
                check=bool(getattr(args, "check", False)),
                home=bool(getattr(args, "cleanup_home", False)),
            )
        if args.command == "init":
            return cmd_init(root)
        if args.command == "mount":
            return cmd_mount(
                root,
                profile_name=args.profile,
                agent_name=getattr(args, "agent", None),
                check=args.check,
            )
        if args.command == "fetch":
            return cmd_fetch(root, host_name=args.host)
        if args.command in (None, "run"):
            extra = list(getattr(args, "extra", []) or [])
            if extra and extra[0] == "--":
                extra = extra[1:]
            return cmd_run(
                root,
                profile_name=getattr(args, "profile", None),
                agent_name=getattr(args, "agent", None),
                host_name=getattr(args, "host", None),
                use_global=bool(getattr(args, "use_global", False)),
                extra=extra,
            )
    except AgentizeError as exc:
        print(f"agentize: {exc}", file=sys.stderr)
        return 1

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
