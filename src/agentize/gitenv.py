"""Commit identity as process environment.

agentize never runs `git config --local`. A tool that writes into `.git/config`
leaves the repository changed after it exits, and the next person to commit
inherits whoever ran the agent last.
"""

from __future__ import annotations

from .config import Profile


def git_env(profile: Profile) -> dict[str, str]:
    """Identity overrides for the child process. Empty when the profile declares none.

    A profile without a `git` block leaves the machine's own identity in charge,
    which is what a human profile wants: it differs per teammate.
    """
    identity = profile.git
    if identity is None:
        return {}

    env: dict[str, str] = {}
    if identity.user_name:
        env["GIT_AUTHOR_NAME"] = identity.user_name
        env["GIT_COMMITTER_NAME"] = identity.user_name
    if identity.user_email:
        env["GIT_AUTHOR_EMAIL"] = identity.user_email
        env["GIT_COMMITTER_EMAIL"] = identity.user_email
    if identity.push_remote:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "remote.pushDefault"
        env["GIT_CONFIG_VALUE_0"] = identity.push_remote
    return env
