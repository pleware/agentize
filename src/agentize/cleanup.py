"""The inverse of `init`: remove what agentize planted, nothing else.

`.agentize/` is always in scope. Launchers go only when their bytes still
match the planted trampoline — a hand-edited file stays. The policy file
and anything `mount` wrote are not ours to delete.

`~/.agentize/` is a separate tree. Only `--home` touches it.
"""

from __future__ import annotations

import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from .session import user_state_dir
from .store_tree import data_dir
from .wrapper import FILES, is_self_checkout


@dataclass(frozen=True)
class CleanupPlan:
    data: Path | None = None
    launchers: tuple[Path, ...] = ()
    home: Path | None = None

    def __bool__(self) -> bool:
        return self.data is not None or bool(self.launchers) or self.home is not None


def planted_launchers(project_root: Path) -> tuple[Path, ...]:
    """Launchers whose content is still exactly what `init` wrote."""
    if is_self_checkout(project_root):
        return ()
    found: list[Path] = []
    for name, text in FILES.items():
        path = project_root / name
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            found.append(path)
    return tuple(found)


def plan_cleanup(project_root: Path, *, home: bool = False) -> CleanupPlan:
    data = data_dir(project_root)
    home_dir = user_state_dir() if home else None
    return CleanupPlan(
        data=data if data.exists() else None,
        launchers=planted_launchers(project_root),
        home=home_dir if home_dir is not None and home_dir.exists() else None,
    )


def describe(plan: CleanupPlan, project_root: Path) -> tuple[str, ...]:
    lines: list[str] = []
    if plan.data is not None:
        lines.append(f"remove {plan.data.relative_to(project_root).as_posix()}")
    for path in plan.launchers:
        lines.append(f"remove launcher {path.name}")
    if plan.home is not None:
        lines.append(f"remove home {plan.home}")
    return tuple(lines)


def apply_cleanup(plan: CleanupPlan) -> None:
    if plan.data is not None:
        _remove_tree(plan.data)
    for path in plan.launchers:
        path.unlink(missing_ok=True)
    if plan.home is not None:
        _remove_tree(plan.home)


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
        return
    if not path.is_dir():
        return

    def _writable(_func, item: str, _exc: object) -> None:
        target = Path(item)
        target.chmod(target.stat().st_mode | stat.S_IWRITE)
        _func(item)

    shutil.rmtree(path, onerror=_writable)
