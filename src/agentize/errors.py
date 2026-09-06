"""One root for everything agentize raises, so callers can catch a single type."""

from __future__ import annotations


class AgentizeError(Exception):
    """Something in the project's setup is wrong. The message is for the user."""


class MountError(AgentizeError):
    """The resolved content cannot be rendered into a host's native layout."""
