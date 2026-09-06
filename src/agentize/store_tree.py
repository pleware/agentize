"""The store tree: where agentize keeps its files.

Policy lives in `agentize.yaml` at the project root, beside `mani.yaml` and
`ignite.toml`. It is committed, and a repository whitelist can name it in one
line like any other root file.

Runtime data lives in `.agentize/`, which ignores itself. Nothing in there
belongs in git, so the project's own `.gitignore` needs no rule for it.

This is not a workspace tree (ignite kinds) and not a toolchain plant.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import CONFIG_NAME

DIR_NAME = ".agentize"
GITIGNORE_NAME = ".gitignore"

GITIGNORE = """\
# Managed by agentize. Runtime data only — nothing here belongs in git.
*
"""


def config_path(project_root: Path) -> Path:
    return project_root / CONFIG_NAME


def data_dir(project_root: Path) -> Path:
    return project_root / DIR_NAME


def host_root(project_root: Path, host: str) -> Path:
    return data_dir(project_root) / "hosts" / host


def host_version_dir(project_root: Path, host: str, pin: str) -> Path:
    return host_root(project_root, host) / "versions" / pin


def host_current_file(project_root: Path, host: str) -> Path:
    return host_root(project_root, host) / "current"


def host_data_dir(project_root: Path, host: str) -> Path:
    return host_root(project_root, host) / "data"


def read_current_pin(project_root: Path, host: str) -> str | None:
    path = host_current_file(project_root, host)
    if not path.is_file():
        return None
    pin = path.read_text(encoding="utf-8").strip()
    return pin or None


def write_current_pin(project_root: Path, host: str, pin: str) -> None:
    path = host_current_file(project_root, host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pin}\n", encoding="utf-8", newline="\n")


def ensure_data_dir(project_root: Path) -> Path:
    """Create `.agentize/` and make it ignore itself. Never touches the root .gitignore."""
    directory = data_dir(project_root)
    directory.mkdir(parents=True, exist_ok=True)
    ignore_file = directory / GITIGNORE_NAME
    if not ignore_file.is_file() or ignore_file.read_text(encoding="utf-8") != GITIGNORE:
        ignore_file.write_text(GITIGNORE, encoding="utf-8", newline="\n")
    return directory


def config_is_ignored(project_root: Path) -> bool:
    """True when git would ignore `agentize.yaml`.

    A deny-by-default repository ignores every root file it does not whitelist,
    so without `!/agentize.yaml` the policy silently never gets committed.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", CONFIG_NAME],
        cwd=project_root,
        capture_output=True,
    )
    return result.returncode == 0
