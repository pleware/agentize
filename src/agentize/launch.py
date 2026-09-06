"""Start an agent host with a profile applied.

Everything except `spawn` is a calculation over strings, so the argv and the
environment can be asserted without starting anything.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import Config, Host, Profile
from .errors import AgentizeError
from .gitenv import git_env
from .install import isolated_binary, path_name
from .store_tree import ensure_data_dir, host_data_dir


def select_host(
    config: Config, requested: str | None, remembered: str | None = None
) -> Host:
    enabled = list(config.enabled_hosts())
    names = [host.name for host in enabled]
    if requested is not None:
        if requested not in names:
            known = ", ".join(sorted(names)) or "none"
            raise AgentizeError(f"host {requested!r} is not enabled (enabled: {known})")
        return config.hosts[requested]
    if remembered is not None and remembered in names:
        return config.hosts[remembered]
    if len(enabled) == 1:
        return enabled[0]
    if not enabled:
        raise AgentizeError("no host is enabled in the configuration")
    if config.default_host is not None:
        return config.default_host
    raise AgentizeError(
        f"more than one host is enabled; name one with --host "
        f"({', '.join(names)}) or mark one default: true"
    )


def isolation_env(project_root: Path, host: str) -> dict[str, str]:
    """A private database per project, instead of the user's one global one."""
    if host != "opencode":
        return {}
    data = host_data_dir(project_root, host).resolve()
    return {
        "OPENCODE_DATA_DIR": str(data),
        "OPENCODE_DB": str(data / "opencode.db"),
        "OPENCODE_STATE_DIR": str(data / "state"),
        "XDG_DATA_HOME": str(data),
    }


def launch_env(
    base: dict[str, str], project_root: Path, profile: Profile, host: str
) -> dict[str, str]:
    env = dict(base)
    env.update(git_env(profile))
    if profile.isolate_data:
        env.update(isolation_env(project_root, host))
    return env


def global_executable(host: str) -> str:
    name = path_name(host)
    found = shutil.which(name)
    if found is None and host == "cursor":
        found = shutil.which("cursor-agent")
    if found is None:
        raise AgentizeError(f"{name} is not on PATH; agentize does not install hosts")
    return found


def executable(project_root: Path, host: Host, *, use_global: bool) -> str:
    if use_global:
        return global_executable(host.name)
    return str(isolated_binary(project_root, host))


def prepare(project_root: Path, profile: Profile, host: str) -> None:
    if profile.isolate_data and host == "opencode":
        ensure_data_dir(project_root)
        (host_data_dir(project_root, host) / "state").mkdir(parents=True, exist_ok=True)


def spawn(project_root: Path, argv: list[str], env: dict[str, str]) -> int:
    return subprocess.run(argv, cwd=project_root, env=env).returncode
