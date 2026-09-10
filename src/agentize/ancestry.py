"""Ancestor discovery and the shared `cascade/` rules that descend.

A project's `source:` tree may hold a `cascade/` directory. Its `.mdc` files
are always-on rules that every descendant inherits, nearest owner first, so a
product can override a binder rule without editing the binder. The resolver
never sees them — they are flat, not layered, and a filename is the whole key.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_NAME, load_config
from .ignite import IGNITE_TOML
from .mani import lists_descendant, load_mani

CASCADE = "cascade"


@dataclass(frozen=True)
class ObservedParent:
    root: Path
    kind: str


@dataclass(frozen=True)
class CascadeRule:
    key: str
    """Basename in `.cursor/rules/`, e.g. `git-index-flags.mdc`."""

    owner: Path
    """Absolute root of the yaml whose `source:` declared this rule."""

    rel: str
    """Path relative to the owner, e.g. `.agents/cascade/git-index-flags.mdc`."""


def read_kind(root: Path) -> str | None:
    path = root / IGNITE_TOML
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    section = data.get("workspace-tree") or data.get("layout")
    if not isinstance(section, dict):
        return None
    kind = section.get("kind")
    return kind if isinstance(kind, str) and kind else None


def infer_kind(root: Path) -> str:
    explicit = read_kind(root)
    if explicit:
        return explicit
    if load_mani(root) is not None:
        return "workspace"
    return "product"


def observed_parents(root: Path) -> tuple[ObservedParent, ...]:
    """Ancestors whose `mani.yaml` lists this checkout, nearest first."""
    here = root.resolve()
    found: list[ObservedParent] = []
    current = here
    while True:
        parent = current.parent
        if parent == current:
            break
        if load_mani(parent) is not None and lists_descendant(parent, here):
            found.append(ObservedParent(root=parent, kind=infer_kind(parent)))
        current = parent
    return tuple(found)


def find_inherit_root(root: Path) -> Path | None:
    """Closest ancestor with `agentize.yaml` whose `mani.yaml` lists `root`."""
    for item in observed_parents(root):
        if (item.root / CONFIG_NAME).is_file():
            return item.root
    return None


def cascade_rules(root: Path) -> tuple[CascadeRule, ...]:
    """The `cascade/` rules for `root`: its own plus every observed ancestor.

    Iteration starts at `root` and walks upward, so the nearest owner wins on a
    filename. Owners without an `agentize.yaml` (or without a `cascade/` dir)
    contribute nothing.
    """
    owners: list[Path] = [root.resolve()]
    owners.extend(item.root for item in observed_parents(root))
    merged: dict[str, CascadeRule] = {}
    for owner in owners:
        config_path = owner / CONFIG_NAME
        if not config_path.is_file():
            continue
        config = load_config(config_path)
        directory = owner / config.source / CASCADE
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.mdc")):
            if not path.is_file():
                continue
            key = path.name
            if key in merged:
                continue
            merged[key] = CascadeRule(
                key=key, owner=owner, rel=path.relative_to(owner).as_posix()
            )
    return tuple(merged[key] for key in sorted(merged))
