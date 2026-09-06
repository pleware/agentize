from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agentize.config import ConfigError, load_config, parse_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def readme_example() -> str:
    """The config block from README.md, so the example cannot drift from the parser."""
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for block in re.findall(r"```yaml\n(.*?)```", text, re.S):
        if "version:" in block:
            return block
    raise AssertionError("README.md has no yaml block containing a config version")


def test_readme_example_parses_fully():
    config = parse_config(yaml.safe_load(readme_example()), origin="README.md")

    assert config.source == Path(".agents")
    assert set(config.hosts) == {"cursor", "opencode", "claude", "codex"}
    assert config.hosts["cursor"].emit_prefix == "auto."
    assert config.hosts["cursor"].pin == "latest"
    assert config.hosts["cursor"].default
    assert config.default_host is config.hosts["cursor"]
    assert config.hosts["opencode"].plugins == ("oh-my-openagent",)
    assert config.hosts["opencode"].pin == "latest"
    assert not config.hosts["claude"].enabled
    assert {host.name for host in config.enabled_hosts()} == {"cursor", "opencode"}

    human = config.profiles["human"]
    assert config.default_profile is human
    assert human.git is None
    php = config.resolve_agent("php")
    assert php.origin == "agent"
    assert php.git is not None
    assert php.git.user_email == "agent@example.com"
    assert php.git.push_remote == "bot"
    assert php.isolate_data
    assert php.mcp == ("postgres",)
    assert php.lsp.names == ("phpantom",)
    go = config.resolve_agent("go")
    assert go.lsp.names == ("gopls",)
    assert config.lsp_servers["phpantom"].command == ("phpantom_lsp", "--stdio")

    assert config.servers["postgres"].command == ("postgres-mcp",)
    assert config.servers["postgres"].env["DATABASE_URL"] == "${env:DATABASE_URL}"
    assert config.servers["github"].is_remote
    assert config.worktree_dir == ".agentize_worktrees"
    assert config.skills_lock is None, "the README no longer advertises a lock file"


def test_a_lock_key_still_loads(tmp_path: Path):
    """Nothing reads it yet, but a project that has one must not fail to load."""
    path = tmp_path / "agentize.yaml"
    path.write_text(
        "version: 1\nsource: .agents\nskills:\n  lock: skills-lock.json\n", encoding="utf-8"
    )
    assert load_config(path).skills_lock == Path("skills-lock.json")


def test_missing_file_names_the_path(tmp_path: Path):
    missing = tmp_path / "config.yaml"
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        load_config(missing)


def test_unknown_version_names_the_supported_one():
    with pytest.raises(ConfigError, match="version 2 is not supported.*understands version 1"):
        parse_config({"version": 2})


def test_missing_version_is_rejected():
    with pytest.raises(ConfigError, match="version None is not supported"):
        parse_config({"source": ".agents"})


def test_malformed_yaml_is_reported(tmp_path: Path):
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\n  bad: [indent\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_profile_referencing_unknown_server():
    raw = {
        "version": 1,
        "profiles": {"agent": {"mcp": ["nope"]}},
        "mcp": {"servers": {"postgres": {"command": ["postgres-mcp"]}}},
    }
    with pytest.raises(ConfigError, match="unknown server 'nope'.*defined: postgres"):
        parse_config(raw)


def test_two_default_profiles_is_an_error():
    raw = {"version": 1, "profiles": {"a": {"default": True}, "b": {"default": True}}}
    with pytest.raises(ConfigError, match="more than one default profile: a, b"):
        parse_config(raw)


def test_server_needs_exactly_one_of_command_or_url():
    both = {
        "version": 1,
        "mcp": {"servers": {"x": {"command": ["a"], "url": "https://example.com"}}},
    }
    with pytest.raises(ConfigError, match="exactly one of command or url"):
        parse_config(both)

    neither = {"version": 1, "mcp": {"servers": {"x": {"env": {"A": "b"}}}}}
    with pytest.raises(ConfigError, match="exactly one of command or url"):
        parse_config(neither)


def test_unknown_git_key_is_rejected():
    raw = {"version": 1, "profiles": {"agent": {"git": {"username": "bot"}}}}
    with pytest.raises(ConfigError, match="git.username is not a known key"):
        parse_config(raw)


def test_addons_is_rejected_in_favour_of_plugins():
    with pytest.raises(ConfigError, match="renamed to 'plugins'"):
        parse_config({"version": 1, "hosts": {"opencode": {"addons": ["omo"]}}})


def test_wrong_types_are_reported_with_location():
    with pytest.raises(ConfigError, match="hosts.cursor.emit_prefix must be a string"):
        parse_config({"version": 1, "hosts": {"cursor": {"emit_prefix": 7}}})

    with pytest.raises(ConfigError, match=r"profiles\.agent\.mcp: expected a list of strings"):
        parse_config({"version": 1, "profiles": {"agent": {"mcp": "postgres"}}})
