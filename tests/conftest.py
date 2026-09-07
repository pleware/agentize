"""Keep mounts from rewriting the developer's ~/.cursor/mcp.json."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_user_mcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "home" / ".cursor" / "mcp.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def fake() -> Path:
        return path

    monkeypatch.setattr("agentize.user_mcp.user_mcp_path", fake)
    monkeypatch.setattr("agentize.cli.user_mcp_path", fake)
    return path
