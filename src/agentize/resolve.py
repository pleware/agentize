"""Merge `shared`, `hosts/<host>` and `profiles/<profile>` into one set of files.

Pure: the caller supplies a listing of paths relative to the source root and gets
back the files to emit. Nothing here touches the filesystem.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .config import Config, ConfigError

SHARED = "shared"
HOSTS = "hosts"
PROFILES = "profiles"


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


def layers_for(host: str | None, profile: str) -> tuple[Layer, ...]:
    """`host=None` resolves the host-neutral set: shared plus the profile."""
    if host is None:
        return (Layer(SHARED, 0), Layer(f"{PROFILES}/{profile}", 2))
    return (
        Layer(SHARED, 0),
        Layer(f"{HOSTS}/{host}", 1),
        Layer(f"{PROFILES}/{profile}", 2),
    )


def resolve(
    config: Config,
    listing: Iterable[str],
    *,
    host: str | None,
    profile: str,
) -> tuple[ResolvedFile, ...]:
    if host is not None:
        _check_host(config, host)
    _check_profile(config, profile)

    layers = layers_for(host, profile)
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


def _check_host(config: Config, host: str) -> None:
    if host not in config.hosts:
        known = ", ".join(sorted(config.hosts)) or "none"
        raise ResolveError(f"unknown host {host!r} (declared: {known})")
    if not config.hosts[host].enabled:
        raise ResolveError(f"host {host!r} is disabled in the configuration")


def _check_profile(config: Config, profile: str) -> None:
    if profile not in config.profiles:
        known = ", ".join(sorted(config.profiles)) or "none"
        raise ResolveError(f"unknown profile {profile!r} (declared: {known})")
