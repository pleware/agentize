"""The current machine, as archive publishers name it."""

from __future__ import annotations

import platform
import sys

from .errors import AgentizeError

OS_NAMES = {"win32": "windows", "darwin": "darwin", "linux": "linux"}
ARCH_NAMES = {
    "amd64": "x64",
    "x86_64": "x64",
    "x64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
}


def host_os(system: str | None = None) -> str:
    raw = (system if system is not None else sys.platform).lower()
    try:
        return OS_NAMES[raw]
    except KeyError as exc:
        raise AgentizeError(f"unsupported operating system {raw!r}") from exc


def host_arch(machine: str | None = None) -> str:
    raw = (machine if machine is not None else platform.machine()).lower()
    try:
        return ARCH_NAMES[raw]
    except KeyError as exc:
        raise AgentizeError(f"unsupported architecture {raw!r}") from exc
