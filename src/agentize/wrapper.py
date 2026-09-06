"""The file you type is not the package. It is a trampoline into `uvx`.

A project commits three tiny launchers (`agentize`, `agentize.ps1`,
`agentize.cmd`). Each run asks `uv` for the current tree from GitHub, so a
clone that is a week old still starts today's agentize. The Python process
never replaces itself.

Inside this repository the same files notice `pyproject.toml` and call
`uv run` instead, so development does not bounce through GitHub.
"""

from __future__ import annotations

from pathlib import Path

from .config import CONFIG_NAME

SOURCE = "git+https://github.com/pleware/agentize.git"
PACKAGE_NAME = "agentize"
NAME_LINE = f'name = "{PACKAGE_NAME}"'

UNIX_NAME = "agentize"
PS1_NAME = "agentize.ps1"
CMD_NAME = "agentize.cmd"

UNIX = f"""\
#!/bin/sh
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -f "$here/pyproject.toml" ] && grep -q '^name = "{PACKAGE_NAME}"' "$here/pyproject.toml"
then
  exec uv run --project "$here" {PACKAGE_NAME} "$@"
fi
if ! command -v uv >/dev/null 2>&1
then
  echo "agentize: uv is not on PATH" >&2
  exit 1
fi
if [ -n "${{AGENTIZE_OFFLINE-}}" ]
then
  exec uvx --offline --from {SOURCE} {PACKAGE_NAME} "$@"
fi
exec uvx --refresh --from {SOURCE} {PACKAGE_NAME} "$@"
"""

PS1 = f"""\
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$pyproject = Join-Path $here "pyproject.toml"
if ((Test-Path $pyproject) -and (
    Select-String -LiteralPath $pyproject -Pattern '^name = "{PACKAGE_NAME}"' -Quiet
)) {{
    & uv run --project $here {PACKAGE_NAME} @args
    exit $LASTEXITCODE
}}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {{
    [Console]::Error.WriteLine("agentize: uv is not on PATH")
    exit 1
}}
$uvx = @()
if ($env:AGENTIZE_OFFLINE) {{
    $uvx += "--offline"
}} else {{
    $uvx += "--refresh"
}}
& uvx @uvx --from {SOURCE} {PACKAGE_NAME} @args
exit $LASTEXITCODE
"""

CMD = """\
@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0agentize.ps1" %*
exit /b %ERRORLEVEL%
"""

FILES = {
    UNIX_NAME: UNIX,
    PS1_NAME: PS1,
    CMD_NAME: CMD,
}


def is_self_checkout(directory: Path) -> bool:
    """True when this folder is the agentize source tree, not a consumer."""
    manifest = directory / "pyproject.toml"
    if not manifest.is_file():
        return False
    return NAME_LINE in manifest.read_text(encoding="utf-8")


def write_wrappers(project_root: Path) -> tuple[Path, ...]:
    """Plant the trampolines next to `agentize.yaml`. Idempotent."""
    written: list[Path] = []
    for name, text in FILES.items():
        path = project_root / name
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current != text:
            path.write_text(text, encoding="utf-8", newline="\n")
        if name == UNIX_NAME:
            path.chmod(path.stat().st_mode | 0o111)
        written.append(path)
    return tuple(written)


def wrapper_ignore_hint() -> str:
    return (
        f"a deny-by-default .gitignore must whitelist the launchers:\n"
        f"  !/{UNIX_NAME}\n"
        f"  !/{PS1_NAME}\n"
        f"  !/{CMD_NAME}\n"
        f"  !/{CONFIG_NAME}"
    )
