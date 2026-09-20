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
