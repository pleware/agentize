"""agentize command line."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_NAME, load_config
from .errors import AgentizeError
from .launch import executable, launch_env, prepare, select_host, spawn
from .layout import config_is_ignored, config_path, ensure_data_dir
from .mount import (
    Plan,
    apply,
    changes,
    plan_agents_md,
    plan_cursor,
    plan_opencode,
)


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
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("init", help=f"report where {CONFIG_NAME} goes and prepare data")

    mount = subcommands.add_parser("mount", help="render rules for each enabled host")
    mount.add_argument("--profile", metavar="NAME", help="profile to render (default: from config)")
    mount.add_argument(
        "--check",
        action="store_true",
        help="report what would change and exit non-zero, without writing",
    )

    run = subcommands.add_parser("run", help="launch a host with the profile applied (default)")
    run.add_argument("--profile", metavar="NAME", help="profile to apply (default: from config)")
    run.add_argument("--host", metavar="NAME", help="host to launch (default: the enabled one)")
    return parser


def cmd_init(root: Path) -> int:
    directory = ensure_data_dir(root)
    config = config_path(root)
    print(f"agentize: policy {config}")
    print(f"agentize: data   {directory}")

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


PLAN_BUILDERS = {"cursor": plan_cursor, "opencode": plan_opencode}


def mount_plans(root: Path, config, profile_name: str) -> list[Plan]:
    plans = [plan_agents_md(root, config, profile_name)]
    for host in config.enabled_hosts():
        builder = PLAN_BUILDERS.get(host.name)
        if builder is None:
            print(f"agentize: {host.name}: no renderer in this build, skipped", file=sys.stderr)
            continue
        plans.append(builder(root, config, profile_name))
    return plans


def cmd_mount(root: Path, *, profile_name: str | None, check: bool) -> int:
    config = load_config(config_path(root))
    profile = config.select_profile(profile_name)
    pending = 0

    for plan in mount_plans(root, config, profile.name):
        lines = changes(root, plan) if check else apply(root, plan)
        for line in lines:
            print(f"  {line}")
        pending += len(lines) if check else 0
        print(f"agentize: [{profile.name}] {plan.label}")

    if check and pending:
        print(f"agentize: {pending} file(s) out of date — run: agentize mount", file=sys.stderr)
        return 1
    return 0


def cmd_run(root: Path, *, profile_name: str | None, host_name: str | None) -> int:
    config = load_config(config_path(root))
    profile = config.select_profile(profile_name)
    host = select_host(config, host_name)

    prepare(root, profile, host)
    env = launch_env(dict(os.environ), root, profile, host)
    argv = [executable(host)]

    print(f"agentize: {host} [{profile.name}]", file=sys.stderr)
    return spawn(root, argv, env)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = (args.directory or Path.cwd()).resolve()

    try:
        if args.command == "init":
            return cmd_init(root)
        if args.command == "mount":
            return cmd_mount(root, profile_name=args.profile, check=args.check)
        if args.command in (None, "run"):
            return cmd_run(
                root,
                profile_name=getattr(args, "profile", None),
                host_name=getattr(args, "host", None),
            )
    except AgentizeError as exc:
        print(f"agentize: {exc}", file=sys.stderr)
        return 1

    parser.print_help(sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
