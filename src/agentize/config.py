"""Load and validate `agentize.yaml`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import AgentizeError

SUPPORTED_VERSION = 1
CONFIG_NAME = "agentize.yaml"
DEFAULT_AGENT = "default"
RESERVED_AGENT_SLUGS = frozenset({"build", "plan"})

REFERENCE = re.compile(r"\$\{[^}]+\}")
SECRET_HINTS = ("token", "secret", "password", "passwd", "credential", "auth", "api_key", "apikey")
NEED_TOOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]*$")


class ConfigError(AgentizeError):
    """The configuration is missing, unreadable, or does not describe a valid setup."""


@dataclass(frozen=True)
class GitIdentity:
    user_name: str | None = None
    user_email: str | None = None
    push_remote: str | None = None


@dataclass(frozen=True)
class LspChoice:
    """What OpenCode should start. `off` writes `lsp: false`."""

    kind: str = "off"
    names: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return self.kind != "off"


LSP_OFF = LspChoice()
LSP_ALL = LspChoice(kind="all")


@dataclass(frozen=True)
class Host:
    name: str
    enabled: bool = True
    default: bool = False
    emit_prefix: str = ""
    plugins: tuple[str, ...] = ()
    """OpenCode plugin specs, in order. Ignored by hosts that have no plugin list."""
    pin: str | None = None
    """Host version. OpenCode and Cursor treat a missing pin or `latest` as
    floating; both update themselves after the first fetch."""


@dataclass(frozen=True)
class Profile:
    name: str
    default: bool = False
    isolate_data: bool = False
    git: GitIdentity | None = None
    mcp: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    lsp: LspChoice = field(default_factory=LspChoice)
    needs: tuple[str, ...] = ()
    """mise tool names (`php@7.4`) to install on `run`. Empty for a human."""
    origin: str = "profile"
    """`profile` reads `.agents/profiles/<name>/`. `agent` reads
    `.agents/agents/default/` then `.agents/agents/<name>/`."""


@dataclass(frozen=True)
class AgentSpec:
    """One slug in `agents:`. Overlay keys are those listed in `present`."""

    present: frozenset[str]
    isolate_data: bool = False
    git: GitIdentity | None = None
    mcp: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    lsp: LspChoice = field(default_factory=LspChoice)
    needs: tuple[str, ...] = ()


@dataclass(frozen=True)
class McpServer:
    name: str
    command: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def is_remote(self) -> bool:
        return self.url is not None


@dataclass(frozen=True)
class LspServer:
    name: str
    command: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    initialization: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False


@dataclass(frozen=True)
class Config:
    version: int
    source: Path
    hosts: dict[str, Host]
    profiles: dict[str, Profile]
    servers: dict[str, McpServer]
    agents: dict[str, AgentSpec] = field(default_factory=dict)
    lsp_servers: dict[str, LspServer] = field(default_factory=dict)
    skills_lock: Path | None = None
    worktree_dir: str | None = None

    @property
    def default_profile(self) -> Profile | None:
        for profile in self.profiles.values():
            if profile.default:
                return profile
        return None

    @property
    def default_host(self) -> Host | None:
        for host in self.hosts.values():
            if host.default and host.enabled:
                return host
        return None

    def enabled_hosts(self) -> tuple[Host, ...]:
        return tuple(host for host in self.hosts.values() if host.enabled)

    def servers_for(self, profile: Profile) -> tuple[McpServer, ...]:
        """The profile's servers, in the order the profile declares them."""
        return tuple(self.servers[name] for name in profile.mcp)

    def lsp_payload(self, profile: Profile) -> bool | dict[str, LspServer]:
        """Value for OpenCode's `lsp` key: false, true, or named servers."""
        if profile.lsp.kind == "off":
            return False
        if profile.lsp.kind == "all":
            return True
        return {name: self.lsp_servers[name] for name in profile.lsp.names}

    def select_profile(self, requested: str | None) -> Profile:
        if requested is not None:
            if requested not in self.profiles:
                known = ", ".join(sorted(self.profiles)) or "none"
                raise ConfigError(f"unknown profile {requested!r} (declared: {known})")
            return self.profiles[requested]
        default = self.default_profile
        if default is None:
            raise ConfigError("no profile is marked default; name one with --profile")
        return default

    def resolve_agent(self, slug: str) -> Profile:
        if slug not in self.agents:
            known = ", ".join(sorted(self.agents)) or "none"
            raise ConfigError(f"unknown agent {slug!r} (declared: {known})")
        if DEFAULT_AGENT not in self.agents:
            raise ConfigError("agents.default is required when agents are declared")
        base = self.agents[DEFAULT_AGENT]
        overlay = self.agents[slug] if slug != DEFAULT_AGENT else AgentSpec(present=frozenset())
        return _materialize_agent(base, overlay, slug)

    def lookup_driver(self, name: str) -> Profile:
        """A profile name, or an agent slug. Profiles win on a name collision."""
        if name in self.profiles:
            return self.profiles[name]
        if name in self.agents:
            return self.resolve_agent(name)
        known = ", ".join(sorted({*self.profiles, *self.agents})) or "none"
        raise ConfigError(f"unknown profile {name!r} (declared: {known})")

    def select_driver(
        self,
        profile_name: str | None,
        agent_name: str | None,
        *,
        last_profile: str | None = None,
        last_agent: str | None = None,
    ) -> Profile:
        if profile_name and agent_name:
            raise ConfigError("pass --profile or --agent, not both")
        if agent_name:
            return self.resolve_agent(agent_name)
        if profile_name:
            return self.select_profile(profile_name)
        if last_agent and last_agent in self.agents:
            return self.resolve_agent(last_agent)
        if last_profile and last_profile in self.profiles:
            return self.select_profile(last_profile)
        if self.default_profile is not None:
            return self.default_profile
        if DEFAULT_AGENT in self.agents:
            return self.resolve_agent(DEFAULT_AGENT)
        raise ConfigError(
            "no profile is marked default; name one with --profile or --agent"
        )


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"no configuration at {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(raw, origin=str(path))


def parse_config(raw: Any, origin: str = "<config>") -> Config:
    data = _mapping(raw, origin)

    version = data.get("version")
    if version != SUPPORTED_VERSION:
        raise ConfigError(
            f"{origin}: version {version!r} is not supported; "
            f"this build understands version {SUPPORTED_VERSION}"
        )

    source = data.get("source", ".agents")
    if not isinstance(source, str):
        raise ConfigError(f"{origin}: source must be a string")

    hosts = _parse_hosts(data.get("hosts"), origin)
    profiles = _parse_profiles(data.get("profiles"), origin)
    servers = _parse_servers(data.get("mcp"), origin)
    lsp_servers = _parse_lsp_servers(data.get("lsp"), origin)
    agents = _parse_agents(data.get("agents"), origin)

    _check_references(profiles, servers, origin)
    _check_agent_block(agents, servers, lsp_servers, origin)
    _check_lsp_references(profiles, lsp_servers, origin)
    _check_single_default(profiles, origin)
    _check_single_default_host(hosts, origin)

    skills = _mapping(data.get("skills"), f"{origin}: skills")
    lock = skills.get("lock")
    if lock is not None and not isinstance(lock, str):
        raise ConfigError(f"{origin}: skills.lock must be a string")

    worktree = _mapping(data.get("worktree"), f"{origin}: worktree")
    worktree_dir = worktree.get("dir")
    if worktree_dir is not None and not isinstance(worktree_dir, str):
        raise ConfigError(f"{origin}: worktree.dir must be a string")

    return Config(
        version=version,
        source=Path(source),
        hosts=hosts,
        profiles=profiles,
        servers=servers,
        agents=agents,
        lsp_servers=lsp_servers,
        skills_lock=Path(lock) if lock else None,
        worktree_dir=worktree_dir,
    )


def _parse_hosts(raw: Any, origin: str) -> dict[str, Host]:
    hosts: dict[str, Host] = {}
    for name, value in _mapping(raw, f"{origin}: hosts").items():
        where = f"{origin}: hosts.{name}"
        body = _mapping(value, where)
        enabled = body.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ConfigError(f"{where}.enabled must be true or false")
        default = body.get("default", False)
        if not isinstance(default, bool):
            raise ConfigError(f"{where}.default must be true or false")
        prefix = body.get("emit_prefix", "")
        if not isinstance(prefix, str):
            raise ConfigError(f"{where}.emit_prefix must be a string")
        if "addons" in body and "plugins" not in body:
            raise ConfigError(
                f"{where}: 'addons' was renamed to 'plugins' "
                "(OpenCode's own word for the list in opencode.json)"
            )
        hosts[name] = Host(
            name=name,
            enabled=enabled,
            default=default,
            emit_prefix=prefix,
            plugins=_str_list(body.get("plugins"), f"{where}.plugins"),
            pin=_optional_str(body.get("pin"), f"{where}.pin"),
        )
    return hosts


def _parse_profiles(raw: Any, origin: str) -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}
    for name, value in _mapping(raw, f"{origin}: profiles").items():
        where = f"{origin}: profiles.{name}"
        body = _mapping(value, where)
        for key in ("default", "isolate_data"):
            if key in body and not isinstance(body[key], bool):
                raise ConfigError(f"{where}.{key} must be true or false")
        profiles[name] = Profile(
            name=name,
            default=bool(body.get("default", False)),
            isolate_data=bool(body.get("isolate_data", False)),
            git=_parse_git(body.get("git"), f"{where}.git"),
            mcp=_str_list(body.get("mcp"), f"{where}.mcp"),
            skills=_str_list(body.get("skills"), f"{where}.skills"),
            lsp=_parse_lsp_choice(body.get("lsp"), f"{where}.lsp")
            if "lsp" in body
            else LSP_OFF,
            origin="profile",
        )
    return profiles


def _parse_agents(raw: Any, origin: str) -> dict[str, AgentSpec]:
    agents: dict[str, AgentSpec] = {}
    mapping = _mapping(raw, f"{origin}: agents")
    if not mapping:
        return agents
    for name, value in mapping.items():
        where = f"{origin}: agents.{name}"
        if name in RESERVED_AGENT_SLUGS:
            raise ConfigError(
                f"{where} collides with OpenCode's built-in agent; pick another slug"
            )
        body = _mapping(value, where)
        if "isolate_data" in body and not isinstance(body["isolate_data"], bool):
            raise ConfigError(f"{where}.isolate_data must be true or false")
        agents[name] = AgentSpec(
            present=frozenset(body),
            isolate_data=bool(body.get("isolate_data", False)),
            git=_parse_git(body.get("git"), f"{where}.git") if "git" in body else None,
            mcp=_str_list(body.get("mcp"), f"{where}.mcp"),
            skills=_str_list(body.get("skills"), f"{where}.skills"),
            lsp=_parse_lsp_choice(body.get("lsp"), f"{where}.lsp")
            if "lsp" in body
            else LSP_OFF,
            needs=_parse_needs(body.get("needs"), f"{where}.needs")
            if "needs" in body
            else (),
        )
    if DEFAULT_AGENT not in agents:
        raise ConfigError(f"{origin}: agents.default is required when agents are declared")
    return agents


def _parse_git(raw: Any, where: str) -> GitIdentity | None:
    git_body = _mapping(raw, where)
    if not git_body:
        return None
    for key in git_body:
        if key not in {"user_name", "user_email", "push_remote"}:
            raise ConfigError(f"{where}.{key} is not a known key")
    return GitIdentity(
        user_name=_optional_str(git_body.get("user_name"), f"{where}.user_name"),
        user_email=_optional_str(git_body.get("user_email"), f"{where}.user_email"),
        push_remote=_optional_str(git_body.get("push_remote"), f"{where}.push_remote"),
    )


def _parse_needs(value: Any, where: str) -> tuple[str, ...]:
    names = _str_list(value, where)
    for name in names:
        if not NEED_TOOL.match(name):
            raise ConfigError(
                f"{where}: {name!r} is not a mise tool name "
                "(letters, digits, and . _ : @ + -)"
            )
    return names


def _parse_lsp_choice(value: Any, where: str) -> LspChoice:
    if value is None or value is False:
        return LSP_OFF
    if value is True:
        return LSP_ALL
    if isinstance(value, list):
        names = _str_list(value, where)
        return LspChoice(kind="names", names=names) if names else LSP_OFF
    raise ConfigError(f"{where} must be true, false, or a list of server names")


def _parse_servers(raw: Any, origin: str) -> dict[str, McpServer]:
    mcp = _mapping(raw, f"{origin}: mcp")
    servers: dict[str, McpServer] = {}
    for name, value in _mapping(mcp.get("servers"), f"{origin}: mcp.servers").items():
        where = f"{origin}: mcp.servers.{name}"
        body = _mapping(value, where)
        command = _str_list(body.get("command"), f"{where}.command")
        url = _optional_str(body.get("url"), f"{where}.url")
        if bool(command) == bool(url):
            raise ConfigError(f"{where} must set exactly one of command or url")
        env = _str_map(body.get("env"), f"{where}.env")
        headers = _str_map(body.get("headers"), f"{where}.headers")
        _check_no_literal_secrets(env, f"{where}.env")
        _check_no_literal_secrets(headers, f"{where}.headers")
        servers[name] = McpServer(
            name=name,
            command=command,
            env=env,
            url=url,
            headers=headers,
        )
    return servers


def _parse_lsp_servers(raw: Any, origin: str) -> dict[str, LspServer]:
    lsp = _mapping(raw, f"{origin}: lsp")
    servers: dict[str, LspServer] = {}
    for name, value in _mapping(lsp.get("servers"), f"{origin}: lsp.servers").items():
        where = f"{origin}: lsp.servers.{name}"
        body = _mapping(value, where)
        disabled = body.get("disabled", False)
        if not isinstance(disabled, bool):
            raise ConfigError(f"{where}.disabled must be true or false")
        command = _str_list(body.get("command"), f"{where}.command")
        if not disabled and not command:
            raise ConfigError(f"{where} must set command unless disabled is true")
        env = _str_map(body.get("env"), f"{where}.env")
        _check_no_literal_secrets(env, f"{where}.env")
        initialization = body.get("initialization")
        if initialization is None:
            init: dict[str, Any] = {}
        else:
            parsed = _jsonish(initialization, f"{where}.initialization")
            if not isinstance(parsed, dict):
                raise ConfigError(f"{where}.initialization must be a mapping")
            init = parsed
        servers[name] = LspServer(
            name=name,
            command=command,
            extensions=_str_list(body.get("extensions"), f"{where}.extensions"),
            env=env,
            initialization=init,
            disabled=disabled,
        )
    return servers


def _materialize_agent(base: AgentSpec, overlay: AgentSpec, name: str) -> Profile:
    isolate = (
        overlay.isolate_data if "isolate_data" in overlay.present else base.isolate_data
    )
    git = overlay.git if "git" in overlay.present else base.git
    if "git" in overlay.present and overlay.git is not None and base.git is not None:
        git = GitIdentity(
            user_name=overlay.git.user_name
            if overlay.git.user_name is not None
            else base.git.user_name,
            user_email=overlay.git.user_email
            if overlay.git.user_email is not None
            else base.git.user_email,
            push_remote=overlay.git.push_remote
            if overlay.git.push_remote is not None
            else base.git.push_remote,
        )
    mcp = overlay.mcp if "mcp" in overlay.present else base.mcp
    skills = overlay.skills if "skills" in overlay.present else base.skills
    lsp = overlay.lsp if "lsp" in overlay.present else base.lsp
    needs = overlay.needs if "needs" in overlay.present else base.needs
    return Profile(
        name=name,
        isolate_data=isolate,
        git=git,
        mcp=mcp,
        skills=skills,
        lsp=lsp,
        needs=needs,
        origin="agent",
    )


def _jsonish(value: Any, where: str) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_jsonish(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        return {str(key): _jsonish(item, f"{where}.{key}") for key, item in value.items()}
    raise ConfigError(f"{where}: expected a JSON value, got {type(value).__name__}")


def _check_no_literal_secrets(values: dict[str, str], where: str) -> None:
    """A secret-shaped key must hold a `${...}` reference, never the value itself.

    This file is committed. A literal here is a leak, not a configuration choice.
    """
    for key, value in values.items():
        lowered = key.lower()
        if any(hint in lowered for hint in SECRET_HINTS) and not REFERENCE.search(value):
            raise ConfigError(
                f"{where}.{key} looks like a secret but holds a literal value. "
                f"Use a reference such as ${{env:{key.upper()}}} — this file is committed."
            )


def _check_mcp_names(names: tuple[str, ...], servers: dict[str, McpServer], where: str) -> None:
    for name in names:
        if name not in servers:
            known = ", ".join(sorted(servers)) or "none"
            raise ConfigError(f"{where} references unknown server {name!r} (defined: {known})")


def _check_lsp_names(choice: LspChoice, servers: dict[str, LspServer], where: str) -> None:
    if choice.kind != "names":
        return
    for name in choice.names:
        if name not in servers:
            known = ", ".join(sorted(servers)) or "none"
            raise ConfigError(
                f"{where} references unknown LSP server {name!r} (defined: {known})"
            )


def _check_references(
    profiles: dict[str, Profile], servers: dict[str, McpServer], origin: str
) -> None:
    for profile in profiles.values():
        _check_mcp_names(
            profile.mcp, servers, f"{origin}: profiles.{profile.name}.mcp"
        )


def _check_lsp_references(
    profiles: dict[str, Profile], lsp_servers: dict[str, LspServer], origin: str
) -> None:
    for profile in profiles.values():
        _check_lsp_names(
            profile.lsp, lsp_servers, f"{origin}: profiles.{profile.name}.lsp"
        )


def _check_agent_block(
    agents: dict[str, AgentSpec],
    servers: dict[str, McpServer],
    lsp_servers: dict[str, LspServer],
    origin: str,
) -> None:
    if not agents:
        return
    for name, spec in agents.items():
        where = f"{origin}: agents.{name}"
        if "mcp" in spec.present:
            _check_mcp_names(spec.mcp, servers, f"{where}.mcp")
        if "lsp" in spec.present:
            _check_lsp_names(spec.lsp, lsp_servers, f"{where}.lsp")
    base = agents[DEFAULT_AGENT]
    for name in agents:
        overlay = agents[name] if name != DEFAULT_AGENT else AgentSpec(present=frozenset())
        merged = _materialize_agent(base, overlay, name)
        _check_mcp_names(merged.mcp, servers, f"{origin}: agents.{name}.mcp")
        _check_lsp_names(merged.lsp, lsp_servers, f"{origin}: agents.{name}.lsp")


def _check_single_default(profiles: dict[str, Profile], origin: str) -> None:
    defaults = [name for name, profile in profiles.items() if profile.default]
    if len(defaults) > 1:
        raise ConfigError(f"{origin}: more than one default profile: {', '.join(sorted(defaults))}")


def _check_single_default_host(hosts: dict[str, Host], origin: str) -> None:
    defaults = [name for name, host in hosts.items() if host.default]
    if len(defaults) > 1:
        raise ConfigError(f"{origin}: more than one default host: {', '.join(sorted(defaults))}")


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _str_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{where}: expected a list of strings")
    return tuple(value)


def _str_map(value: Any, where: str) -> dict[str, str]:
    body = _mapping(value, where)
    for key, item in body.items():
        if not isinstance(item, str):
            raise ConfigError(f"{where}.{key}: expected a string")
    return dict(body)


def _optional_str(value: Any, where: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{where}: expected a string")
    return value
