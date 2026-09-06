from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.errors import AgentizeError
from agentize.ignite import (
    DEFAULT_KIT_URL,
    KitPolicy,
    ensure_toolchain,
    kit_dir,
    load_kit_policy,
    plant_kit,
    run_ensure,
    toolchain_env,
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_kit_policy_defaults_url(tmp_path: Path):
    write(tmp_path / "ignite.toml", '[kit]\npin = "fee062f"\n')
    policy = load_kit_policy(tmp_path)
    assert policy.pin == "fee062f"
    assert policy.url == DEFAULT_KIT_URL


def test_kit_policy_reads_url(tmp_path: Path):
    write(
        tmp_path / "ignite.toml",
        '[kit]\npin = "v1"\nurl = "https://example.com/ignite.git"\n',
    )
    policy = load_kit_policy(tmp_path)
    assert policy.pin == "v1"
    assert policy.url == "https://example.com/ignite.git"


def test_missing_ignite_toml_names_the_file(tmp_path: Path):
    with pytest.raises(AgentizeError, match="ignite.toml"):
        load_kit_policy(tmp_path)


def test_kit_section_without_pin_is_rejected(tmp_path: Path):
    write(tmp_path / "ignite.toml", '[workspace-tree]\nkind = "binder"\n')
    with pytest.raises(AgentizeError, match=r"\[kit\] pin"):
        load_kit_policy(tmp_path)


def test_plant_kit_skips_clone_when_ensure_exists(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    dest = kit_dir("abc")
    write(dest / "ensure.sh", "#!/bin/sh\n")
    calls: list[list[str]] = []

    def run(argv, check=False):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    policy = KitPolicy(pin="abc", url=DEFAULT_KIT_URL, source=tmp_path / "ignite.toml")
    assert plant_kit(policy, run=run) == dest
    assert calls == []


def test_plant_kit_clones_then_checks_out(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    dest = kit_dir("abc")
    calls: list[list[str]] = []

    def run(argv, check=False):
        calls.append(list(argv))
        if argv[1] == "clone":
            write(Path(argv[-1]) / "ensure.sh", "#!/bin/sh\n")
        return subprocess.CompletedProcess(argv, 0)

    policy = KitPolicy(pin="abc", url=DEFAULT_KIT_URL, source=tmp_path / "ignite.toml")
    assert plant_kit(policy, run=run) == dest
    assert calls[0][:3] == ["git", "clone", DEFAULT_KIT_URL]
    assert calls[1][:4] == ["git", "-C", str(dest), "checkout"]
    assert calls[1][-1] == "abc"


def test_run_ensure_passes_needs(tmp_path: Path, monkeypatch):
    kit = tmp_path / "kit"
    write(kit / "ensure.sh", "#!/bin/sh\n")
    monkeypatch.setattr("agentize.ignite.posix_shell", lambda: ["sh"])
    seen: list[list[str]] = []

    def run(argv, check=False):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    run_ensure(kit, tmp_path, ("php@7.4", "phpantom"), run=run)
    assert seen[0][-3:] == [str(tmp_path), "php@7.4", "phpantom"]
    assert seen[0][-4].endswith("ensure.sh")


def test_toolchain_env_expands_path(tmp_path: Path, monkeypatch):
    kit = tmp_path / "kit"
    write(kit / "env" / "env.sh", "#!/bin/sh\n")
    monkeypatch.setattr("agentize.ignite.posix_shell", lambda: ["sh"])
    monkeypatch.setattr(
        "agentize.ignite.subprocess.check_output",
        lambda argv, text: (
            'export MISE_DATA_DIR="/data"\n'
            'export PATH="/data/shims:/stack/bin:$PATH"\n'
            "unset GOROOT\n"
        ),
    )
    env = toolchain_env(kit, tmp_path, {"PATH": "/usr/bin", "GOROOT": "gone"})
    assert env["MISE_DATA_DIR"] == "/data"
    assert env["PATH"] == "/data/shims:/stack/bin:/usr/bin"
    assert "GOROOT" not in env


def test_run_agent_without_ignite_toml_fails(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "hosts:\n  opencode: {}\n"
        "agents:\n  default: {}\n  php: {}\n",
    )
    monkeypatch.setattr("agentize.cli.spawn", lambda root, argv, env: 0)
    monkeypatch.setattr(
        "agentize.cli.executable", lambda root, host, use_global: f"/bin/{host.name}"
    )
    assert main(["-C", str(tmp_path), "run", "--agent", "php"]) == 1
    assert "ignite.toml" in capsys.readouterr().err


def test_run_profile_does_not_call_ensure(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "hosts:\n  opencode: {}\n"
        "profiles:\n  human:\n    default: true\n",
    )
    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("human run must not ensure ignite")

    monkeypatch.setattr("agentize.cli.ensure_toolchain", boom)
    monkeypatch.setattr("agentize.cli.spawn", lambda root, argv, env: 0)
    monkeypatch.setattr(
        "agentize.cli.executable", lambda root, host, use_global: f"/bin/{host.name}"
    )
    assert main(["-C", str(tmp_path), "run", "--profile", "human"]) == 0
    assert called["n"] == 0


def test_ensure_toolchain_wires_plant_and_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENTIZE_HOME", str(tmp_path / "home"))
    write(tmp_path / "ignite.toml", '[kit]\npin = "abc"\n')
    kit = kit_dir("abc")
    write(kit / "ensure.sh", "#!/bin/sh\n")
    write(kit / "env" / "env.sh", "#!/bin/sh\n")
    monkeypatch.setattr("agentize.ignite.run_ensure", lambda *a, **k: None)
    monkeypatch.setattr(
        "agentize.ignite.toolchain_env",
        lambda kit_path, root, base: {"MISE_DATA_DIR": "/data"},
    )
    env = ensure_toolchain(tmp_path, ("php@8.3",), {"PATH": "/usr/bin"})
    assert env["MISE_DATA_DIR"] == "/data"
