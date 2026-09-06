"""The last host that ran in this directory — and, as a fallback, on this machine.

`agentize` with no flags should just start. The committed `agentize.yaml` is the
wrong place for that memory: writing it on every launch would show up as a git
diff. The pointer lives next to the other machine state, under `.agentize/`.

A brand-new empty directory has no project file yet, so a copy also sits in
the user's `~/.agentize/last.yaml` (or `$AGENTIZE_HOME`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .layout import DIR_NAME, data_dir, ensure_data_dir

LAST_NAME = "last.yaml"
HOME_ENV = "AGENTIZE_HOME"


@dataclass(frozen=True)
class LastRun:
    host: str | None = None
    profile: str | None = None
    use_global: bool = False


def user_state_dir() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else Path.home() / DIR_NAME


def last_path(project_root: Path) -> Path:
    return data_dir(project_root) / LAST_NAME


def user_last_path() -> Path:
    return user_state_dir() / LAST_NAME


def load_last(project_root: Path) -> LastRun:
    """Project file wins field-by-field; the user file fills the gaps."""
    user = _read(user_last_path())
    project = _read(last_path(project_root))
    return LastRun(
        host=project.host or user.host,
        profile=project.profile or user.profile,
        use_global=project.use_global if project.host else user.use_global,
    )


def remember(project_root: Path, last: LastRun) -> None:
    ensure_data_dir(project_root)
    _write(last_path(project_root), last)
    home = user_state_dir()
    home.mkdir(parents=True, exist_ok=True)
    _write(user_last_path(), last)


def _read(path: Path) -> LastRun:
    if not path.is_file():
        return LastRun()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return LastRun()
    if not isinstance(raw, dict):
        return LastRun()
    host = raw.get("host")
    profile = raw.get("profile")
    return LastRun(
        host=host if isinstance(host, str) and host else None,
        profile=profile if isinstance(profile, str) and profile else None,
        use_global=bool(raw.get("use_global", False)),
    )


def _write(path: Path, last: LastRun) -> None:
    body = {
        "host": last.host,
        "profile": last.profile,
        "use_global": last.use_global,
    }
    path.write_text(
        yaml.safe_dump(body, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
