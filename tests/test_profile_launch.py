"""Profiles, git identity and launch preparation. Nothing here spawns a host."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agentize.config import ConfigError, parse_config
from agentize.errors import AgentizeError
from agentize.gitenv import git_env
from agentize.launch import isolation_env, launch_env, mcp_process_env, prepare, select_host
from agentize.store_tree import host_data_dir

CONFIG = parse_config(
    {
        "version": 1,
        "hosts": {"opencode": {}, "claude": {"enabled": False}},
        "profiles": {
            "human": {},
            "agent": {
                "isolate_data": True,
                "git": {
                    "user_name": "acme-agent",
                    "user_email": "agent@example.com",
                    "push_remote": "bot",
                },
            },
        },
    }
)

HUMAN = CONFIG.profiles["human"]
AGENT = CONFIG.profiles["agent"]


# --- profile selection ---


def test_no_profile_named_is_an_error():
    with pytest.raises(ConfigError, match="a profile is required"):
        CONFIG.select_profile(None)


def test_an_explicit_profile_is_accepted():
    assert CONFIG.select_profile("agent") is AGENT


def test_an_unknown_profile_lists_the_declared_ones():
    with pytest.raises(ConfigError, match="unknown profile 'robot'.*declared: agent, human"):
        CONFIG.select_profile("robot")


def test_a_profile_must_be_named_even_without_a_default():
    config = parse_config({"version": 1, "profiles": {"a": {}, "b": {}}})
    with pytest.raises(ConfigError, match="a profile is required"):
        config.select_profile(None)


# --- git identity ---


def test_a_profile_without_git_inherits_the_machine_identity():
    assert git_env(HUMAN) == {}


def test_identity_is_set_for_both_author_and_committer():
    env = git_env(AGENT)
    assert env["GIT_AUTHOR_NAME"] == "acme-agent"
    assert env["GIT_COMMITTER_NAME"] == "acme-agent"
    assert env["GIT_AUTHOR_EMAIL"] == "agent@example.com"
    assert env["GIT_COMMITTER_EMAIL"] == "agent@example.com"


def test_push_remote_travels_as_config_environment_not_a_file_edit():
    env = git_env(AGENT)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "remote.pushDefault"
    assert env["GIT_CONFIG_VALUE_0"] == "bot"


def test_a_partial_identity_sets_only_what_it_declares():
    config = parse_config(
        {"version": 1, "profiles": {"p": {"git": {"push_remote": "bot"}}}}
    )
    env = git_env(config.profiles["p"])
    assert "GIT_AUTHOR_NAME" not in env
    assert env["GIT_CONFIG_VALUE_0"] == "bot"


def test_the_repository_config_is_never_written(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    config_file = tmp_path / ".git" / "config"
    before = config_file.read_bytes()

    launch_env({}, tmp_path, AGENT, "opencode")

    assert config_file.read_bytes() == before


def test_the_identity_actually_reaches_git(tmp_path: Path):
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)

    env = launch_env(dict(os.environ), tmp_path, AGENT, "opencode")
    subprocess.run(["git", "commit", "-qm", "test"], cwd=tmp_path, env=env, check=True)

    author = subprocess.run(
        ["git", "log", "-1", "--pretty=%an <%ae>"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert author == "acme-agent <agent@example.com>"


# --- host selection ---


def test_no_host_named_is_an_error():
    with pytest.raises(AgentizeError, match="a host is required"):
        select_host(CONFIG, None)


def test_an_explicit_host_is_accepted():
    assert select_host(CONFIG, "opencode").name == "opencode"


def test_a_disabled_host_cannot_be_launched():
    with pytest.raises(AgentizeError, match="host 'claude' is not enabled"):
        select_host(CONFIG, "claude")


def test_an_unknown_host_is_not_enabled():
    with pytest.raises(AgentizeError, match="is not enabled"):
        select_host(CONFIG, "nope")


# --- data isolation ---


def test_isolated_profile_gets_a_project_local_database(tmp_path: Path):
    env = launch_env({}, tmp_path, AGENT, "opencode")
    expected = host_data_dir(tmp_path, "opencode").resolve()

    assert env["OPENCODE_DB"] == str(expected / "opencode.db")
    assert env["XDG_DATA_HOME"] == str(expected)


def test_a_shared_profile_keeps_the_global_database(tmp_path: Path):
    assert "OPENCODE_DB" not in launch_env({}, tmp_path, HUMAN, "opencode")


def test_isolation_is_opencode_specific(tmp_path: Path):
    assert isolation_env(tmp_path, "cursor") == {}


def test_prepare_creates_the_data_directory(tmp_path: Path):
    prepare(tmp_path, AGENT, "opencode")
    assert (host_data_dir(tmp_path, "opencode") / "state").is_dir()


def test_prepare_creates_nothing_for_a_shared_profile(tmp_path: Path):
    prepare(tmp_path, HUMAN, "opencode")
    assert not host_data_dir(tmp_path, "opencode").exists()


def test_the_base_environment_is_not_mutated(tmp_path: Path):
    base = {"PATH": "/usr/bin"}
    launch_env(base, tmp_path, AGENT, "opencode")
    assert base == {"PATH": "/usr/bin"}


def test_mcp_refs_are_copied_onto_the_process_env():
    config = parse_config(
        {
            "version": 1,
            "mcp": {
                "servers": {
                    "db": {
                        "command": ["srv"],
                        "env": {
                            "DATABASE_URL": "${env:DATABASE_URL}",
                            "LOG_LEVEL": "debug",
                        },
                    }
                }
            },
        }
    )
    servers = (config.servers["db"],)
    env = mcp_process_env(servers, {"DATABASE_URL": "postgres://local"})
    assert env == {"DATABASE_URL": "postgres://local"}


def test_empty_mcp_refs_are_not_copied():
    config = parse_config(
        {
            "version": 1,
            "mcp": {
                "servers": {
                    "db": {"command": ["srv"], "env": {"DATABASE_URL": "${env:DATABASE_URL}"}}
                }
            },
        }
    )
    assert mcp_process_env((config.servers["db"],), {"DATABASE_URL": ""}) == {}


def test_launch_injects_mcp_refs_only_for_opencode(tmp_path: Path):
    config = parse_config(
        {
            "version": 1,
            "mcp": {
                "servers": {
                    "db": {
                        "command": ["srv"],
                        "env": {"AGENT_REPO": "${env:REPO}"},
                    }
                }
            },
        }
    )
    servers = (config.servers["db"],)
    base = {"REPO": "C:\\work\\app"}
    opencode_env = launch_env(base, tmp_path, HUMAN, "opencode", servers=servers)
    cursor_env = launch_env(base, tmp_path, HUMAN, "cursor", servers=servers)
    assert opencode_env["AGENT_REPO"] == "C:\\work\\app"
    assert "AGENT_REPO" not in cursor_env


def test_hermes_launch_sets_profile_home(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentize.hosts.hermes.user_hermes_root", lambda: tmp_path / ".hermes")
    env = launch_env({}, tmp_path, HUMAN, "hermes")
    assert env["HERMES_HOME"] == str(tmp_path / ".hermes" / "profiles" / "agentize-human")


def test_isolated_hermes_uses_desktop_profile(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentize.hosts.hermes.user_hermes_root", lambda: tmp_path / ".hermes")
    env = launch_env({}, tmp_path, AGENT, "hermes")
    assert env["HERMES_HOME"] == str(tmp_path / ".hermes" / "profiles" / "agentize-agent")


def test_prepare_creates_the_hermes_profile_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("agentize.hosts.hermes.user_hermes_root", lambda: tmp_path / ".hermes")
    prepare(tmp_path, HUMAN, "hermes")
    assert (tmp_path / ".hermes" / "profiles" / "agentize-human").is_dir()
