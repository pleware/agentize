"""`mount --profile-all`: every declared identity, none overwriting another.

One identity at a time stays the default: the same file names, one set of
skills. The flag adds the identity label to every name that would otherwise
collide, so the prune set is a union and no identity wins by order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentize.cli import main
from agentize.config import load_config
from agentize.mount import apply
from agentize.user_mcp import collect_all_user_mcp_servers, plan_user_mcp

CONFIG = """\
version: 1
source: .agents
hosts:
  cursor: {enabled: true, user_mcp: false}
  opencode: {enabled: true}
profiles:
  human:
    default: true
    mcp: [pg]
    skills: [review]
agents:
  default:
    mcp: [pg]
    skills: [review]
  php:
    mcp: [pg]
mcp:
  servers:
    pg: {command: [postgres-mcp]}
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    write(tmp_path / "agentize.yaml", CONFIG)
    write(tmp_path / ".agents" / "shared" / "style.mdc", "shared\n")
    write(tmp_path / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")
    write(tmp_path / ".agents" / "agents" / "php" / "php-only.mdc", "php\n")
    return tmp_path


def names(directory: Path) -> list[str]:
    return sorted(item.name for item in directory.iterdir()) if directory.is_dir() else []


def mcp_keys(project: Path, rel: str = ".cursor/mcp.json") -> list[str]:
    data = json.loads((project / rel).read_text(encoding="utf-8"))
    return sorted(data.get("mcpServers") or data.get("mcp") or {})


# --- one file per identity ---


def test_every_identity_gets_its_own_rule_files(project: Path):
    assert main(["-C", str(project), "mount", "--profile-all"]) == 0

    assert names(project / ".cursor" / "rules") == [
        "agentize.auto.generated.agent.style.mdc",
        "agentize.auto.generated.do-not-edit.mdc",
        "agentize.auto.generated.human.style.mdc",
        "agentize.auto.generated.php.php-only.mdc",
        "agentize.auto.generated.php.style.mdc",
    ]


def test_skills_land_in_per_identity_directories(project: Path):
    main(["-C", str(project), "mount", "--profile-all"])

    assert names(project / ".cursor" / "skills") == [
        "agentize.auto.generated.agent.review",
        "agentize.auto.generated.human.review",
        "agentize.auto.generated.php.review",
    ]
    assert names(project / ".opencode" / "skills") == [
        "agentize.auto.generated.agent.review",
        "agentize.auto.generated.human.review",
        "agentize.auto.generated.php.review",
    ]


def test_mcp_keys_say_which_identity_owns_them(project: Path):
    main(["-C", str(project), "mount", "--profile-all"])

    assert mcp_keys(project) == ["agent.pg", "human.pg", "php.pg"]
    assert mcp_keys(project, "opencode.json") == ["agent.pg", "human.pg", "php.pg"]


def test_agents_md_carries_one_section_per_identity(project: Path):
    main(["-C", str(project), "mount", "--profile-all"])

    text = (project / "AGENTS.md").read_text(encoding="utf-8")
    assert "### human (profile)" in text
    assert "### agent (slug)" in text
    assert "### php (slug)" in text
    assert text.count("[style.mdc]") == 3


def test_the_pass_is_idempotent_and_check_is_clean(project: Path):
    main(["-C", str(project), "mount", "--profile-all"])

    assert main(["-C", str(project), "mount", "--profile-all", "--check"]) == 0


def test_one_identity_prunes_the_qualified_files(project: Path):
    main(["-C", str(project), "mount", "--profile-all"])

    assert main(["-C", str(project), "mount", "--profile", "human"]) == 0

    assert names(project / ".cursor" / "rules") == [
        "agentize.auto.generated.do-not-edit.mdc",
        "agentize.auto.generated.style.mdc",
    ]
    assert names(project / ".cursor" / "skills") == ["agentize.auto.generated.review"]
    assert mcp_keys(project) == ["pg"]


def test_profile_all_with_an_explicit_identity_is_refused(project: Path, capsys):
    assert main(["-C", str(project), "mount", "--profile-all", "--agent", "php"]) == 1

    assert "not both" in capsys.readouterr().err


# --- cascade and the user file ---


def test_cascade_plants_every_identity_into_one_file(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "child").mkdir(parents=True)
    write(ws / "agentize.yaml", CONFIG)
    write(ws / ".agents" / "shared" / "style.mdc", "shared\n")
    write(ws / ".agents" / "shared" / "skills" / "review" / "SKILL.md", "# review\n")
    write(ws / "mani.yaml", yaml.safe_dump({"projects": {"child": {"path": "child"}}}))

    assert main(["-C", str(ws), "mount", "--profile-all"]) == 0

    data = json.loads((ws / "child" / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert sorted(data["mcpServers"]) == ["agent.pg", "human.pg", "php.pg"]


def test_the_user_file_keys_carry_the_identity(tmp_path: Path):
    write(tmp_path / "agentize.yaml", CONFIG)
    config = load_config(tmp_path / "agentize.yaml")

    wanted = collect_all_user_mcp_servers(tmp_path, config, config.all_identities())
    assert sorted(wanted) == ["agentize-agent.pg", "agentize-human.pg", "agentize-php.pg"]

    target = tmp_path / "home" / ".cursor" / "mcp.json"
    apply(tmp_path / "home", plan_user_mcp(wanted, path=target))
    assert sorted(json.loads(target.read_text(encoding="utf-8"))["mcpServers"]) == [
        "agentize-agent.pg",
        "agentize-human.pg",
        "agentize-php.pg",
    ]
