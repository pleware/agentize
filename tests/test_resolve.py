"""The resolver is pure. No test here touches the filesystem."""

from __future__ import annotations

import pytest

from agentize.config import parse_config
from agentize.resolve import ResolveError, resolve

CONFIG = parse_config(
    {
        "version": 1,
        "hosts": {"cursor": {}, "opencode": {}, "claude": {"enabled": False}},
        "profiles": {"human": {"default": True}, "agent": {}},
    }
)


def keys(listing, host="cursor", profile="human"):
    return [item.key for item in resolve(CONFIG, listing, host=host, profile=profile)]


def winner(listing, key, host="cursor", profile="human"):
    for item in resolve(CONFIG, listing, host=host, profile=profile):
        if item.key == key:
            return item
    raise AssertionError(f"{key} did not resolve")


def test_shared_layer_alone():
    assert keys(["shared/core/style.mdc"]) == ["core/style.mdc"]


def test_host_layer_alone():
    assert keys(["hosts/cursor/only.mdc"]) == ["only.mdc"]


def test_profile_layer_alone():
    assert keys(["profiles/human/only.mdc"]) == ["only.mdc"]


def test_other_hosts_and_profiles_are_not_included():
    listing = [
        "shared/a.mdc",
        "hosts/opencode/b.mdc",
        "profiles/agent/c.mdc",
    ]
    assert keys(listing) == ["a.mdc"]


def test_paths_outside_the_three_layers_are_ignored():
    listing = ["skills/code-review/SKILL.md", "README.md", "shared/a.mdc"]
    assert keys(listing) == ["a.mdc"]


def test_host_overrides_shared():
    listing = ["shared/rule.mdc", "hosts/cursor/rule.mdc"]
    assert winner(listing, "rule.mdc").layer == "hosts/cursor"


def test_profile_overrides_shared():
    listing = ["shared/rule.mdc", "profiles/human/rule.mdc"]
    assert winner(listing, "rule.mdc").layer == "profiles/human"


def test_profile_overrides_host():
    listing = ["hosts/cursor/rule.mdc", "profiles/human/rule.mdc"]
    assert winner(listing, "rule.mdc").layer == "profiles/human"


def test_three_layers_resolve_to_the_profile():
    listing = ["shared/rule.mdc", "hosts/cursor/rule.mdc", "profiles/human/rule.mdc"]
    resolved = resolve(CONFIG, listing, host="cursor", profile="human")
    assert len(resolved) == 1
    assert resolved[0].layer == "profiles/human"
    assert resolved[0].path == "profiles/human/rule.mdc"


def test_a_collision_yields_one_file_not_two():
    listing = ["shared/rule.mdc", "profiles/human/rule.mdc"]
    assert keys(listing) == ["rule.mdc"]


def test_nested_keys_collide_on_the_full_relative_path():
    listing = ["shared/php/style.mdc", "profiles/human/shell/style.mdc"]
    assert keys(listing) == ["php/style.mdc", "shell/style.mdc"]


def test_input_order_does_not_change_the_result():
    forward = ["shared/rule.mdc", "hosts/cursor/rule.mdc", "profiles/human/rule.mdc"]
    assert winner(forward, "rule.mdc").layer == winner(list(reversed(forward)), "rule.mdc").layer


def test_output_is_sorted_by_key():
    listing = ["shared/z.mdc", "shared/a.mdc", "shared/m.mdc"]
    assert keys(listing) == ["a.mdc", "m.mdc", "z.mdc"]


def test_windows_separators_are_accepted():
    assert keys([r"shared\core\style.mdc"]) == ["core/style.mdc"]


def test_layer_root_without_a_file_is_skipped():
    assert keys(["shared/"]) == []


def test_unknown_host_is_an_error_not_an_empty_result():
    expected = "unknown host 'codex'.*declared: claude, cursor, opencode"
    with pytest.raises(ResolveError, match=expected):
        resolve(CONFIG, ["shared/a.mdc"], host="codex", profile="human")


def test_unknown_profile_is_an_error_not_an_empty_result():
    with pytest.raises(ResolveError, match="unknown profile 'robot'.*declared: agent, human"):
        resolve(CONFIG, ["shared/a.mdc"], host="cursor", profile="robot")


def test_disabled_host_is_refused():
    with pytest.raises(ResolveError, match="host 'claude' is disabled"):
        resolve(CONFIG, ["shared/a.mdc"], host="claude", profile="human")
