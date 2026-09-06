"""Start an agent host with a profile applied.

Everything except `spawn` is a pure calculation over strings, so the argv and the
environment can be asserted without starting anything.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import Config, Profile
from .errors import AgentizeError
from .gitenv import git_env
from .layout import data_dir, ensure_data_dir

EXECUTABLES = {"opencode": "opencode", "cursor": "cursor"}


def select_host(config: Config, requested: str | None) -> str:
    enabled = [host.name for host in config.enabled_hosts()]
    if requested is not None:
        if requested not in enabled:
            known = ", ".join(sorted(enabled)) or "none"
            raise AgentizeError(f"host {requested!r} is not enabled (enabled: {known})")
        return requested
    if len(enabled) == 1:
        return enabled[0]
    if not enabled:
        raise AgentizeError("no host is enabled in the configuration")
    raise AgentizeError(
        f"more than one host is enabled; name one with --host: {', '.join(enabled)}"
    )


def host_data_dir(project_root: Path, host: str) -> Path:
    return data_dir(project_root) / host


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


def executable(host: str) -> str:
    name = EXECUTABLES.get(host, host)
    found = shutil.which(name)
    if found is None:
        raise AgentizeError(f"{name} is not on PATH; agentize does not install hosts")
    return found


def prepare(project_root: Path, profile: Profile, host: str) -> None:
    if profile.isolate_data and host == "opencode":
        ensure_data_dir(project_root)
        (host_data_dir(project_root, host) / "state").mkdir(parents=True, exist_ok=True)


def spawn(project_root: Path, argv: list[str], env: dict[str, str]) -> int:
    return subprocess.run(argv, cwd=project_root, env=env).returncode
