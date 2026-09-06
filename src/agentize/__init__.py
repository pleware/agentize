"""One project config. Every agent host."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agentize")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["__version__"]
