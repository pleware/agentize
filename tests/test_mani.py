from __future__ import annotations

from pathlib import Path

import yaml

from agentize.config import McpServer
from agentize.mani import discover_up_and_down, find_with_file
from agentize.markers import bind_server_markers, resolve_marker_value

MARKER = "tools/sync.py"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def mani_projects(root: Path, **paths: str) -> None:
    projects = {name: {"path": rel} for name, rel in paths.items()}
    write(root / "mani.yaml", yaml.safe_dump({"projects": projects}))


def nested_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    binder = tmp_path / "env"
    workspace = binder / "acme-workspace"
    product = workspace / "shop-backend"
    family = workspace / "dev-mcp" / "orchestrator"
    family.mkdir(parents=True)
    write(product / MARKER, "# sync\n")
    mani_projects(binder, acme="acme-workspace")
    mani_projects(workspace, shop="shop-backend", family="dev-mcp")
    return binder, family, product


def test_discover_from_family_and_binder(tmp_path: Path):
    binder, family, product = nested_tree(tmp_path)
    want = product.resolve()
    assert find_with_file(binder, MARKER) == want
    assert discover_up_and_down(family, MARKER) == want
    assert discover_up_and_down(binder, MARKER) == want


def test_marker_resolves_via_mani(tmp_path: Path):
    _binder, family, product = nested_tree(tmp_path)
    assert resolve_marker_value(f"${{marker:{MARKER}}}", family) == str(product.resolve())


def test_unresolved_marker_is_dropped(tmp_path: Path):
    start = tmp_path / "empty"
    start.mkdir()
    assert resolve_marker_value(f"${{marker:{MARKER}}}", start) is None
    bound = bind_server_markers(
        McpServer(name="orch", env={"REPO": f"${{marker:{MARKER}}}", "KEEP": "ok"}),
        start,
    )
    assert "REPO" not in bound.env
    assert bound.env["KEEP"] == "ok"
