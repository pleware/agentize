"""Plant the ignite kit and ask it to install mise tools.

Agentize does not download PHP. It clones the pinned kit, runs `ensure.sh`
(no mani clones), and prepends the mise shims to PATH.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AgentizeError
from .session import user_state_dir

DEFAULT_KIT_URL = "https://github.com/pleware/ignite.git"
IGNITE_TOML = "ignite.toml"
EXPORT = re.compile(r'^export ([A-Za-z_][A-Za-z0-9_]*)="(.*)"\s*$')
UNSET = re.compile(r"^unset ([A-Za-z_][A-Za-z0-9_]*)\s*$")


@dataclass(frozen=True)
class KitPolicy:
    pin: str
    url: str
    source: Path


def load_kit_policy(project_root: Path) -> KitPolicy:
    path = project_root / IGNITE_TOML
    if not path.is_file():
        raise AgentizeError(
            f"missing {path}; an agent run needs ignite. Add ignite.toml with [kit] pin."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise AgentizeError(f"{path}: {exc}") from exc
    kit = data.get("kit")
    if not isinstance(kit, dict):
        raise AgentizeError(f"{path}: [kit] pin is required when an agent runs")
    pin = kit.get("pin")
    if not isinstance(pin, str) or not pin.strip():
        raise AgentizeError(f"{path}: [kit] needs pin (git tag, branch, or commit)")
    url = kit.get("url") or DEFAULT_KIT_URL
    if not isinstance(url, str) or not url.strip():
        raise AgentizeError(f"{path}: [kit] url must be a git remote")
    return KitPolicy(pin=pin.strip(), url=url.strip(), source=path)


def kit_dir(pin: str) -> Path:
    return user_state_dir() / "ignite" / pin


def posix_shell() -> list[str]:
    if os.name != "nt":
        return ["sh"]
    roots = (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    )
    for root in roots:
        bash = Path(root) / "Git" / "bin" / "bash.exe"
        if bash.is_file():
            return [str(bash)]
    raise AgentizeError("Git Bash not found. Install Git for Windows and retry.")


def plant_kit(
    policy: KitPolicy, *, run: Callable[..., Any] = subprocess.run
) -> Path:
    dest = kit_dir(policy.pin)
    if (dest / "ensure.sh").is_file():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise AgentizeError(
            f"ignite kit at {dest} is not usable (missing ensure.sh). Delete it and retry."
        )
    try:
        run(["git", "clone", policy.url, str(dest)], check=True)
        run(["git", "-C", str(dest), "checkout", "--detach", policy.pin], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AgentizeError(
            f"could not plant ignite {policy.pin} from {policy.url}: {exc}"
        ) from exc
    if not (dest / "ensure.sh").is_file():
        raise AgentizeError(
            f"ignite kit {policy.pin} has no ensure.sh; pin a commit that has it"
        )
    return dest


def run_ensure(
    kit: Path,
    project_root: Path,
    needs: tuple[str, ...],
    *,
    run: Callable[..., Any] = subprocess.run,
) -> None:
    script = kit / "ensure.sh"
    argv = [*posix_shell(), str(script), str(project_root), *needs]
    try:
        run(argv, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AgentizeError(f"ignite ensure failed: {exc}") from exc


def toolchain_env(kit: Path, project_root: Path, base: dict[str, str]) -> dict[str, str]:
    script = kit / "env" / "env.sh"
    if not script.is_file():
        raise AgentizeError(f"ignite kit at {kit} has no env/env.sh")
    try:
        raw = subprocess.check_output(
            [*posix_shell(), str(script), str(project_root)],
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AgentizeError(f"ignite env failed: {exc}") from exc
    env: dict[str, str] = {}
    for line in raw.splitlines():
        unset = UNSET.match(line)
        if unset:
            env.pop(unset.group(1), None)
            continue
        match = EXPORT.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if key == "PATH" and "$PATH" in value:
            value = value.replace("$PATH", base.get("PATH", ""))
        env[key] = value
    return env


def ensure_toolchain(
    project_root: Path,
    needs: tuple[str, ...],
    base: dict[str, str],
) -> dict[str, str]:
    """Clone the kit if needed, run ensure.sh, return env to merge into launch."""
    policy = load_kit_policy(project_root)
    kit = plant_kit(policy)
    run_ensure(kit, project_root, needs)
    return toolchain_env(kit, project_root, base)
