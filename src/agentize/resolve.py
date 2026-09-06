"""Merge `shared`, `hosts/<host>` and the active identity into one set of files.

Pure: the caller supplies a listing of paths relative to the source root and gets
back the files to emit. Nothing here touches the filesystem.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .config import Config, ConfigError, Profile

SHARED = "shared"
HOSTS = "hosts"
PROFILES = "profiles"
AGENTS = "agents"
DEFAULT_AGENT = "default"


class ResolveError(ConfigError):
    """The configuration does not describe the host or profile that was asked for."""


@dataclass(frozen=True)
class Layer:
    name: str
    rank: int


@dataclass(frozen=True)
class ResolvedFile:
    key: str
    """Path relative to the layer root. Two layers collide when their keys match."""

    path: str
    """Path relative to the source root."""

    layer: str


def layers_for(host: str | None, identity: Profile) -> tuple[Layer, ...]:
    """`host=None` resolves the host-neutral set: shared plus the identity."""
    trailing = _identity_layers(identity)
    if host is None:
        return (Layer(SHARED, 0), *trailing)
    return (Layer(SHARED, 0), Layer(f"{HOSTS}/{host}", 1), *trailing)


def _identity_layers(identity: Profile) -> tuple[Layer, ...]:
    if identity.origin == "agent":
        layers = [Layer(f"{AGENTS}/{DEFAULT_AGENT}", 2)]
        if identity.name != DEFAULT_AGENT:
            layers.append(Layer(f"{AGENTS}/{identity.name}", 3))
        return tuple(layers)
    return (Layer(f"{PROFILES}/{identity.name}", 2),)


def resolve(
    config: Config,
    listing: Iterable[str],
    *,
    host: str | None,
    profile: str | None = None,
    identity: Profile | None = None,
) -> tuple[ResolvedFile, ...]:
    driver = identity if identity is not None else _driver_from_name(config, profile)
    if host is not None:
        _check_host(config, host)

    layers = layers_for(host, driver)
    best: dict[str, tuple[int, ResolvedFile]] = {}

    for raw in listing:
        path = raw.replace("\\", "/")
        for layer in layers:
            prefix = f"{layer.name}/"
            if not path.startswith(prefix):
                continue
            key = path[len(prefix) :]
            if not key:
                continue
            current = best.get(key)
            if current is None or layer.rank >= current[0]:
                best[key] = (layer.rank, ResolvedFile(key=key, path=path, layer=layer.name))
            break

    return tuple(resolved for _key, (_rank, resolved) in sorted(best.items()))


def _driver_from_name(config: Config, name: str | None) -> Profile:
    if name is None:
        raise ResolveError("a profile or agent identity is required")
    if name in config.profiles:
        return config.profiles[name]
    if name in config.agents:
        return config.resolve_agent(name)
    known = ", ".join(sorted(config.profiles)) or "none"
    raise ResolveError(f"unknown profile {name!r} (declared: {known})")


def _check_host(config: Config, host: str) -> None:
    if host not in config.hosts:
        known = ", ".join(sorted(config.hosts)) or "none"
        raise ResolveError(f"unknown host {host!r} (declared: {known})")
    if not config.hosts[host].enabled:
        raise ResolveError(f"host {host!r} is disabled in the configuration")
