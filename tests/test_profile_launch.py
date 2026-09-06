"""Profiles, git identity and launch preparation. Nothing here spawns a host."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agentize.config import ConfigError, parse_config
from agentize.errors import AgentizeError
from agentize.gitenv import git_env
from agentize.launch import isolation_env, launch_env, prepare, select_host
from agentize.store_tree import host_data_dir

CONFIG = parse_config(
    {
        "version": 1,
        "hosts": {"opencode": {}, "claude": {"enabled": False}},
        "profiles": {
            "human": {"default": True},
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


def test_the_default_profile_is_used_when_none_is_named():
    assert CONFIG.select_profile(None) is HUMAN


def test_an_explicit_profile_overrides_the_default():
    assert CONFIG.select_profile("agent") is AGENT


def test_an_unknown_profile_lists_the_declared_ones():
    with pytest.raises(ConfigError, match="unknown profile 'robot'.*declared: agent, human"):
        CONFIG.select_profile("robot")


def test_without_a_default_a_profile_must_be_named():
    config = parse_config({"version": 1, "profiles": {"a": {}, "b": {}}})
    with pytest.raises(ConfigError, match="no profile is marked default"):
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


def test_the_only_enabled_host_needs_no_flag():
    assert select_host(CONFIG, None).name == "opencode"


def test_a_disabled_host_cannot_be_launched():
    with pytest.raises(AgentizeError, match="host 'claude' is not enabled"):
        select_host(CONFIG, "claude")


def test_several_enabled_hosts_require_a_choice():
    config = parse_config({"version": 1, "hosts": {"cursor": {}, "opencode": {}}})
    with pytest.raises(AgentizeError, match="more than one host is enabled"):
        select_host(config, None)


def test_a_default_host_breaks_the_first_run_tie():
    config = parse_config(
        {"version": 1, "hosts": {"cursor": {"default": True}, "opencode": {}}}
    )
    assert select_host(config, None).name == "cursor"


def test_two_default_hosts_are_rejected():
    with pytest.raises(ConfigError, match="more than one default host"):
        parse_config(
            {
                "version": 1,
                "hosts": {
                    "cursor": {"default": True},
                    "opencode": {"default": True},
                },
            }
        )


def test_memory_beats_the_default_host():
    config = parse_config(
        {"version": 1, "hosts": {"cursor": {"default": True}, "opencode": {}}}
    )
    assert select_host(config, None, "opencode").name == "opencode"


def test_the_remembered_host_breaks_the_tie():
    config = parse_config({"version": 1, "hosts": {"cursor": {}, "opencode": {}}})
    assert select_host(config, None, "opencode").name == "opencode"


def test_a_flag_beats_the_remembered_host():
    config = parse_config({"version": 1, "hosts": {"cursor": {}, "opencode": {}}})
    assert select_host(config, "cursor", "opencode").name == "cursor"


def test_a_stale_memory_is_ignored_if_that_host_is_off():
    config = parse_config(
        {"version": 1, "hosts": {"cursor": {}, "opencode": {"enabled": False}}}
    )
    assert select_host(config, None, "opencode").name == "cursor"


def test_no_enabled_host_is_an_error():
    config = parse_config({"version": 1, "hosts": {"cursor": {"enabled": False}}})
    with pytest.raises(AgentizeError, match="no host is enabled"):
        select_host(config, None)


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
