"""Read child paths from a committed `mani.yaml`. No clone. No filesystem crawl."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .errors import AgentizeError

MANI_NAME = "mani.yaml"
SELF_PATHS = frozenset({".", "", "./"})


class ManiError(AgentizeError):
    """The registry is present but not a mapping we can walk."""


def load_mani(root: Path) -> dict[str, Any] | None:
    path = root / MANI_NAME
    if not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ManiError(f"{path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ManiError(f"{path}: expected a mapping, got {type(raw).__name__}")
    return raw


def child_relpaths(root: Path) -> tuple[str, ...]:
    """Project `path` values that are not this root. Missing dirs stay in the list."""
    data = load_mani(root)
    if data is None:
        return ()
    projects = data.get("projects")
    if projects is None:
        return ()
    if not isinstance(projects, dict):
        raise ManiError(f"{root / MANI_NAME}: projects must be a mapping")
    out: list[str] = []
    seen: set[str] = set()
    for name, body in projects.items():
        if not isinstance(body, dict):
            raise ManiError(f"{root / MANI_NAME}: projects.{name} must be a mapping")
        rel = body.get("path")
        if not isinstance(rel, str) or rel in SELF_PATHS:
            continue
        key = Path(rel).as_posix()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return tuple(out)


def child_dirs(root: Path) -> tuple[Path, ...]:
    """Resolved child directories that exist. Missing paths are skipped, not an error."""
    base = root.resolve()
    found: list[Path] = []
    for rel in child_relpaths(root):
        path = (base / rel).resolve()
        if path.is_dir() and path != base:
            found.append(path)
    return tuple(found)


def lists_descendant(registry: Path, target: Path) -> bool:
    """True when `target` is a listed child of `registry`, or under one."""
    base = registry.resolve()
    here = target.resolve()
    for rel in child_relpaths(registry):
        child = (base / rel).resolve()
        if here == child or child in here.parents:
            return True
    return False


def find_with_file(root: Path, rel: str | Path) -> Path | None:
    """First directory at or under `root` (via `mani.yaml` only) that holds `rel`.

    Does not `os.walk`. Names of children do not matter — only registry paths.
    Binder → workspace → product of any company is the same walk.
    """
    marker = Path(rel)
    if marker.is_absolute() or not str(rel):
        return None
    seen: set[Path] = set()
    stack = [root.resolve()]
    while stack:
        here = stack.pop()
        if here in seen:
            continue
        seen.add(here)
        if (here / marker).is_file():
            return here
        stack.extend(reversed(child_dirs(here)))
    return None


def discover_up_and_down(start: Path, rel: str | Path) -> Path | None:
    """Walk ancestors of `start`; at each one, search that node and its registry.

    Finds a marker whether `start` is a binder, a company workspace, a product,
    or a nested family checkout. Does not guess `parents[N]` or a folder name.
    """
    current = start.resolve()
    seen: set[Path] = set()
    while current not in seen:
        seen.add(current)
        found = find_with_file(current, rel)
        if found is not None:
            return found
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None
