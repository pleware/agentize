from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentize.cli import main
from agentize.config import ConfigError, parse_config
from agentize.hosts import opencode

CONFIG = """\
version: 1
source: .agents
hosts:
  opencode: {}
profiles:
  human: {}
provider:
  myprovider:
    npm: "@ai-sdk/openai-compatible"
    name: My Provider
    options:
      baseURL: https://api.example.test/v1
      apiKey: ${env:MY_API_KEY}
    models:
      my-model:
        name: My Model
experimental:
  mcp_timeout: 30000
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")
    return tmp_path


def rendered(project: Path) -> dict:
    return json.loads((project / "opencode.json").read_text(encoding="utf-8"))


# --- provider / experimental sections ---


def test_provider_is_rendered_with_opencode_env_syntax(project: Path):
    assert main(["-C", str(project), "mount", "--host", "opencode", "--profile", "human"]) == 0
    provider = rendered(project)["provider"]["myprovider"]

    assert provider["options"]["apiKey"] == "{env:MY_API_KEY}"
    assert provider["options"]["baseURL"] == "https://api.example.test/v1"
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["models"]["my-model"]["name"] == "My Model"


def test_experimental_is_rendered(project: Path):
    assert main(["-C", str(project), "mount", "--host", "opencode", "--profile", "human"]) == 0
    assert rendered(project)["experimental"] == {"mcp_timeout": 30000}


ARBITRARY_EXPERIMENTAL = """\
version: 1
source: .agents
hosts:
  opencode: {}
profiles:
  human: {}
experimental:
  mcp_timeout: 180000
  flag: true
  ratio: 1.5
  nothing: null
  text: napis
  nested:
    a:
      b:
        c: [1, 2, {d: glebiej}]
  a.dotted.key: 1
  "key with spaces": 2
  "key:with:colons": 3
  1: numeral-as-key
  allowed_tools: [read, write]
  empty_section: {}
"""


def test_experimental_accepts_any_key_and_any_json_value(tmp_path: Path):
    """The block is OpenCode's, so agentize never keeps a list of allowed keys."""
    write(tmp_path / "agentize.yaml", ARBITRARY_EXPERIMENTAL)
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(tmp_path), "mount", "--host", "opencode", "--profile", "human"]) == 0

    assert rendered(tmp_path)["experimental"] == {
        "mcp_timeout": 180000,
        "flag": True,
        "ratio": 1.5,
        "nothing": None,
        "text": "napis",
        "nested": {"a": {"b": {"c": [1, 2, {"d": "glebiej"}]}}},
        "a.dotted.key": 1,
        "key with spaces": 2,
        "key:with:colons": 3,
        "1": "numeral-as-key",
        "allowed_tools": ["read", "write"],
        "empty_section": {},
    }


def test_a_bare_yaml_date_renders_as_iso_text(tmp_path: Path):
    """PyYAML turns `2026-09-20` into a date; JSON has no such type, and refusing the
    mount over it is the difference between "any key" and "any value"."""
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  opencode: {}\n"
        "profiles:\n"
        "  human: {}\n"
        "experimental:\n"
        "  updated_at: 2026-09-20\n"
        "  at: 2026-09-20T04:53:00\n"
        '  quoted: "2026-09-20"\n',
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")

    assert main(["-C", str(tmp_path), "mount", "--host", "opencode", "--profile", "human"]) == 0

    experimental = rendered(tmp_path)["experimental"]
    assert experimental["updated_at"] == "2026-09-20"
    assert experimental["at"] == "2026-09-20T04:53:00"
    assert experimental["quoted"] == "2026-09-20"  # quoted and bare agree


def test_a_value_with_no_json_form_names_the_fix():
    with pytest.raises(ConfigError, match="has no JSON form"):
        parse_config({"version": 1, "experimental": {"blob": b"hi"}})


def test_absent_sections_leave_existing_keys_untouched(tmp_path: Path):
    write(
        tmp_path / "agentize.yaml",
        "version: 1\n"
        "source: .agents\n"
        "hosts:\n"
        "  opencode: {}\n"
        "profiles:\n"
        "  human:\n",
    )
    write(tmp_path / ".agents" / "shared" / "style.mdc", "style\n")
    write(
        tmp_path / "opencode.json",
        json.dumps(
            {"provider": {"kept": {"name": "Kept"}}, "experimental": {"mcp_timeout": 1}}
        ),
    )

    assert main(["-C", str(tmp_path), "mount", "--host", "opencode", "--profile", "human"]) == 0
    data = json.loads((tmp_path / "opencode.json").read_text(encoding="utf-8"))
    assert data["provider"] == {"kept": {"name": "Kept"}}
    assert data["experimental"] == {"mcp_timeout": 1}


# --- secrets never reach a committed file ---


def test_a_literal_secret_in_provider_options_is_rejected():
    raw = {
        "version": 1,
        "provider": {"myprovider": {"options": {"apiKey": "sk-live-abc"}}},
    }
    with pytest.raises(ConfigError, match="looks like a secret but holds a literal value"):
        parse_config(raw)


def test_a_provider_reference_is_accepted():
    raw = {
        "version": 1,
        "provider": {"myprovider": {"options": {"apiKey": "${env:MY_API_KEY}"}}},
    }
    parsed = parse_config(raw).provider["myprovider"]["options"]["apiKey"]
    assert parsed == "${env:MY_API_KEY}"


def test_ordinary_provider_options_are_left_alone():
    raw = {
        "version": 1,
        "provider": {"myprovider": {"options": {"baseURL": "https://api.example.test/v1"}}},
    }
    assert (
        parse_config(raw).provider["myprovider"]["options"]["baseURL"]
        == "https://api.example.test/v1"
    )


def test_provider_must_be_a_mapping_of_mappings():
    with pytest.raises(ConfigError, match="provider.myprovider"):
        parse_config({"version": 1, "provider": {"myprovider": "nope"}})


# --- translation helper ---


def test_translate_env_refs_is_recursive():
    value = {"a": ["${env:X}", {"b": "${env:Y}"}], "c": 3}
    assert opencode.translate_env_refs(value) == {
        "a": ["{env:X}", {"b": "{env:Y}"}],
        "c": 3,
    }


def test_translate_env_refs_leaves_other_text_alone():
    assert opencode.translate_env_refs("https://api.example.test/v1") == (
        "https://api.example.test/v1"
    )
    assert opencode.translate_env_refs("{file:./key}") == "{file:./key}"
