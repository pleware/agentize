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

REFERENCE = re.compile(r"\$\{[^}]+\}")
SECRET_HINTS = ("token", "secret", "password", "passwd", "credential", "auth", "api_key", "apikey")


class ConfigError(AgentizeError):
    """The configuration is missing, unreadable, or does not describe a valid setup."""


@dataclass(frozen=True)
class GitIdentity:
    user_name: str | None = None
    user_email: str | None = None
    push_remote: str | None = None


@dataclass(frozen=True)
class Host:
    name: str
    enabled: bool = True
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
class Config:
    version: int
    source: Path
    hosts: dict[str, Host]
    profiles: dict[str, Profile]
    servers: dict[str, McpServer]
    skills_lock: Path | None = None
    worktree_dir: str | None = None

    @property
    def default_profile(self) -> Profile | None:
        for profile in self.profiles.values():
            if profile.default:
                return profile
        return None

    def enabled_hosts(self) -> tuple[Host, ...]:
        return tuple(host for host in self.hosts.values() if host.enabled)

    def servers_for(self, profile: Profile) -> tuple[McpServer, ...]:
        """The profile's servers, in the order the profile declares them."""
        return tuple(self.servers[name] for name in profile.mcp)

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

    _check_references(profiles, servers, origin)
    _check_single_default(profiles, origin)

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
        git_body = _mapping(body.get("git"), f"{where}.git")
        git = None
        if git_body:
            for key in git_body:
                if key not in {"user_name", "user_email", "push_remote"}:
                    raise ConfigError(f"{where}.git.{key} is not a known key")
            git = GitIdentity(
                user_name=_optional_str(git_body.get("user_name"), f"{where}.git.user_name"),
                user_email=_optional_str(git_body.get("user_email"), f"{where}.git.user_email"),
                push_remote=_optional_str(git_body.get("push_remote"), f"{where}.git.push_remote"),
            )
        profiles[name] = Profile(
            name=name,
            default=bool(body.get("default", False)),
            isolate_data=bool(body.get("isolate_data", False)),
            git=git,
            mcp=_str_list(body.get("mcp"), f"{where}.mcp"),
            skills=_str_list(body.get("skills"), f"{where}.skills"),
        )
    return profiles


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


def _check_references(
    profiles: dict[str, Profile], servers: dict[str, McpServer], origin: str
) -> None:
    for profile in profiles.values():
        for name in profile.mcp:
            if name not in servers:
                known = ", ".join(sorted(servers)) or "none"
                raise ConfigError(
                    f"{origin}: profiles.{profile.name}.mcp references unknown server "
                    f"{name!r} (defined: {known})"
                )


def _check_single_default(profiles: dict[str, Profile], origin: str) -> None:
    defaults = [name for name, profile in profiles.items() if profile.default]
    if len(defaults) > 1:
        raise ConfigError(f"{origin}: more than one default profile: {', '.join(sorted(defaults))}")


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
