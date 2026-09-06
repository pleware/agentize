# agentize

[![CI](https://github.com/pleware/agentize/actions/workflows/ci.yml/badge.svg)](https://github.com/pleware/agentize/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/pleware/agentize/branch/main/graph/badge.svg)](https://codecov.io/gh/pleware/agentize)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](LICENSE)

One project config. Every agent host.

> **Status:** Cursor and OpenCode work. Claude Code and Codex are deferred.
> `run` starts the project's isolated copy of a host, not whatever happens to
> be on `PATH`. Both hosts track `latest` and update themselves after the
> first `fetch`.

## Install

Run the matching one-liner in the project root. That is the whole install.

If `uv` / `uvx` is missing, the script downloads the current GitHub release,
checks the `.sha256` sidecar, and puts both binaries in `~/.local/bin`
(and on your user PATH on Windows). Then it downloads the three launchers
and checks those hashes against `scripts/checksums.txt`. A failed hash
writes nothing.

Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.sh | sh
```

macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install-macos.sh | sh
```

Windows (PowerShell or Command Prompt):

```bat
cmd /c "curl.exe -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.ps1 -o %TEMP%\agentize-install.ps1 && powershell -NoProfile -ExecutionPolicy Bypass -File %TEMP%\agentize-install.ps1"
```

One line on purpose: Command Prompt has no `iex`, and PowerShell turns
`curl.exe` output into an array that `iex` will not accept. This downloads
with `curl.exe` (so WinINET cannot serve a stale `irm` copy) and runs the
script as a file. After that, `.\agentize fetch` works in both shells.

The files it writes (`agentize`, `agentize.ps1`, `agentize.cmd`) are
trampolines, not the package. They call
`uvx --refresh --from git+https://github.com/pleware/agentize.git`. Then add
`agentize.yaml` and run `./agentize fetch` (Windows: `.\agentize fetch`).

---

## The problem

You wire up an MCP server in Cursor. Then again in Claude Code. Then again in
Codex, in TOML this time. The rules that explain how your repository works get
copy-pasted between hosts and quietly drift apart.

Then there is the part nobody configures at all:

**Your agent and you are not the same user.**

The agent commits under your name, or you scrub the attribution afterwards. It
loads the same MCP servers you do, including the one wired to a production
database. It gets your issue-tracker credentials, because nothing ever said it
should not.

Most setups cannot express *"the bot gets less than the human"* — the config
has only one axis: which host.

## What agentize does

agentize adds the missing axis. You declare **who** (profile) and **where**
(host) once, and it renders the native config each host expects.

```sh
./agentize               # trampoline: uvx refreshes this tool, then runs it
./agentize fetch              # first copy of each host into .agentize/hosts/
./agentize run --agent php    # plant ignite if needed, ensure tools, mount, start
./agentize run --global       # escape hatch: the host on PATH
./agentize mount --agent php  # render without starting
./agentize mount --check      # CI gate: fail if the rendered output is stale
./agentize cleanup       # remove .agentize/ and planted launchers
./agentize --cleanup --home  # also remove ~/.agentize/
```

`run --agent` requires `ignite.toml` with `[kit] pin`. If this machine has
no kit, agentize clones it under `~/.agentize/ignite/<pin>/` and runs
`ensure.sh` with that slug's `needs`. PHP versions stay in `mise.toml`.
A human `--profile` does not touch ignite.

`agentize init` plants three launchers (`agentize`, `agentize.ps1`,
`agentize.cmd`) next to `agentize.yaml`. They are not the package. They call
`uvx --refresh --from git+https://github.com/pleware/agentize.git`, so a week-old
clone still starts today's build. `AGENTIZE_OFFLINE=1` skips the check and uses
the cache. Inside this repository the same files call `uv run` instead, so
development does not go through GitHub.

`agentize cleanup` (or `--cleanup`) is the inverse of `init`: it deletes
`.agentize/` and any launcher whose bytes still match the planted trampoline.
A hand-edited launcher stays. `agentize.yaml` stays. Files `mount` wrote
(`.cursor/`, `opencode.json`, `AGENTS.md`) stay. `--home` also deletes
`~/.agentize/` (`$AGENTIZE_HOME` if set). `--check` reports without deleting.

A deny-by-default `.gitignore` needs the launchers whitelisted, same as the
policy file:

```gitignore
!/agentize
!/agentize.ps1
!/agentize.cmd
!/agentize.yaml
```

`cursor` here is the **agent CLI** (`agent` / `cursor-agent`), not the desktop
editor. `run` never copies a shim from `PATH`. A missing copy is an error that
names `agentize fetch`. After that first copy, leave the binary alone: Cursor
Agent (`agent update`) and OpenCode refresh themselves in the same tree.

The last host and profile are stored in `.agentize/last.yaml` (and a copy under
`~/.agentize/`). That is why a bare `agentize` is enough the second time — and
why it still works in a directory that has no `agentize.yaml` yet. The
committed file is never rewritten on launch.

## Two axes

|            | `cursor` | `opencode` | `claude` | `codex` |
| ---------- | -------- | ---------- | -------- | ------- |
| **human**  | ✓        |            |          |         |
| **agent**  |          | ✓          |          | ✓       |

A **host** is the program. A **profile** is who is driving it. They are
independent: an agent can run in Cursor, a human can run in Codex.

Today these get conflated. A file called "OpenCode rules" ends up containing
*"always push to the bot's remote"* — which is a rule about the **bot**, not
about **OpenCode**. It works only until the first human opens that host.

## Layering

Content composes in three layers. Later wins.

```
shared  →  hosts/<host>  →  profiles/<profile>
shared  →  hosts/<host>  →  agents/default  →  agents/<slug>
```

A **profile** is who is driving (a human, today). An **agent slug** is which
bot (`php`, `go`, `docs`). `agents.default` is the shared bot base; a slug
overrides only the keys it sets. `needs` is the mise tool list for that
slug (`php@7.4` during a migration). Versions stay in `mise.toml`. Not a
matrix of host × slug.

```
.agents/
  shared/            every host, every profile
    core/style.mdc     a rule
    skills/review/     a skill: any directory holding SKILL.md
  hosts/cursor/      any profile, in Cursor
  hosts/opencode/
  profiles/human/    any host, driven by a human
  profiles/agent/    any host, driven by a bot
```

### Skills

A skill layers like everything else, with one difference: the **directory** is
the unit. The winning layer supplies the whole skill, never a mixture — a
`SKILL.md` from one layer describing helper files from another is not a skill
anybody wrote.

Each host receives its own copy, in a directory only that host reads:
`.cursor/skills` and `.opencode/skills`. agentize never writes into
`.agents/skills`, `.claude/skills` or `.codex/skills`, which several hosts scan
in common — so a skill intended for one host cannot be picked up by another, and
there is nothing to clean up after the fact.

A profile or agent slug can narrow the set:

```yaml
agents:
  default:
    skills: [review]     # omit the key to get every skill the layers resolve
```

agentize copies skills the project already owns. It does not fetch them —
`npx skills` and the host marketplaces do that.

## Configuration

```yaml
# agentize.yaml
version: 1

source: .agents

hosts:
  cursor:
    default: true               # bare `agentize` starts this until last.yaml remembers
    emit_prefix: auto.
    pin: latest                 # or omit; Cursor Agent updates itself
  opencode:
    pin: latest                 # or omit; OpenCode updates itself
    plugins:
      - oh-my-openagent          # first; OpenCode installs it at startup
  claude: { enabled: false }
  codex:  { enabled: false }

profiles:
  human:
    default: true
    # No git block: a human's identity differs per teammate.
    # It comes from the machine file, not the repository.
    mcp: [postgres, github, sentry]
    skills: [code-review, idea-refine]

agents:
  default:                        # every bot inherits this
    git:
      user_name: acme-agent
      user_email: agent@example.com
      push_remote: bot
    isolate_data: true
    mcp: [postgres]               # no issue tracker, no deploy tooling
    skills: [code-review]
    lsp: false
    needs: [php@8.3]
  php:
    lsp: [phpantom]
    needs: [php@8.3, phpantom]
  php74:
    needs: [php@7.4]
  go:
    lsp: [gopls]
    needs: [go]

lsp:
  servers:
    phpantom:
      command: [phpantom_lsp, --stdio]
      extensions: [.php]
    gopls:
      command: [gopls]
      extensions: [.go]

mcp:
  servers:
    postgres:
      command: [postgres-mcp]
      env:
        DATABASE_URL: ${env:DATABASE_URL}    # a reference, never a value
    github:
      url: https://api.example.com/mcp
      headers:
        Authorization: Bearer ${env:GITHUB_TOKEN}
    sentry:
      url: https://mcp.sentry.dev/mcp

worktree:
  dir: .agentize_worktrees
```

Secrets are never written into a project file. `${env:...}` is a reference;
values are injected into the host process at launch, from a machine-level file
outside the repository.

Git identity is set as process environment. agentize never runs
`git config --local`.

### Store tree

```
<project>/
  agentize             launcher — commit this (uvx trampoline)
  agentize.ps1
  agentize.cmd
  agentize.yaml        policy — commit this (pin: latest is the default shape)
  .agentize/           machine state — ignores itself
    last.yaml              last host, profile and agent slug — not committed
    hosts/
      opencode/
        versions/latest/     unpacked fetch; the host may overwrite
        current              pointer (text, not a symlink)
        data/                isolated OpenCode database
      cursor/                same shape; the binary inside is the agent CLI
  .agents/             rules and project-owned skills — commit these
```

Policy is one file at the project root, beside `mani.yaml` and `ignite.toml`.
A repository that whitelists what it tracks names it in one line, exactly like
its neighbours:

```gitignore
!/agentize.yaml
```

`.agentize/` holds only machine state, so it ignores itself with a `.gitignore`
containing `*` — the same trick `uv` uses for `.venv`. Your project needs no
rule for it, and agentize never edits a `.gitignore` the project owns.

`agentize init` refuses to continue when `agentize.yaml` sits behind an ignore
rule, because a policy nobody can commit is worse than no policy at all.

### Hosts and versions

`pin: latest` (or omitting `pin`) is the default for Cursor Agent and OpenCode.
Both programs update themselves. agentize installs them once into
`.agentize/hosts/<name>/versions/latest/` and does not fight a later overwrite.

`agentize fetch` is that first copy. If the `latest` tree already looks
installed, fetch leaves it alone so a self-update is not replaced by an older
archive. A numbered pin still skips when that exact version is already present.

Cursor has no `/latest/` download URL. The first fetch reads today's build id
from `https://cursor.com/install`, then unpacks that archive into `latest`.
OpenCode uses GitHub's `releases/latest` redirect.

A concrete pin (`pin: "1.18.4"` or `pin: "2026.09.02-c22c1a3"`) is the escape
hatch: fetch that tag, and `run` refuses if the `current` pointer does not
match.

OpenCode plugins are a list on the host, not a profile. `mount` writes them
into `opencode.json` as `plugin`. The first predefined entry is
[Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent)
(`oh-my-openagent`; `omo` is an alias). OpenCode installs the npm package
itself at startup — agentize does not.

YAML for the source because it nests and takes comments. The output formats
are not a choice — each host dictates its own.

## What agentize does not do

This is the short list on purpose. Most of this problem is already solved.

| Not built here            | Why                                             |
| ------------------------- | ----------------------------------------------- |
| A skill format            | [Agent Skills](https://agentskills.io) is an open standard |
| A skill registry          | `npx skills` and host marketplaces exist        |
| A rules format            | `AGENTS.md` is read by every host                |
| An MCP server schema      | Each host defines one; agentize translates      |
| Language servers          | Pin Intelephense / PHPantom / gopls in the product `mise.toml`. agentize names the command |
| Agent authorization       | The MCP spec is standardizing agent identity    |
| Toolchain versions        | `mise.toml` + ignite. `needs` on a slug is the mise tool list; versions stay in mise |
| Git hook installation     | Same. agentize only exposes the profile hooks read |

What is left is narrow: one source, four dialects, plus the profile axis for
the hosts that lack it.

## Host support

| | Cursor | Claude Code | Codex | OpenCode |
| --- | --- | --- | --- | --- |
| Project MCP file | `.cursor/mcp.json` | `.mcp.json` | `.codex/config.toml` | `opencode.json` |
| Format | JSON | JSON | TOML | JSON |
| Disable one server | UI toggle only | `disabledMcpjsonServers` | `enabled = false` | rendered whole |
| Tool allowlist | `.cursor/cli.json` | permission rules | `enabled_tools` | — |
| Env interpolation | `${env:...}` | — | `env:VAR` | — |
| Native profiles | no | no | **yes** | no |

Codex already has profiles. agentize generalizes that model to the hosts that
do not.

### A limitation worth knowing up front

Cursor merges `~/.cursor/mcp.json` with `.cursor/mcp.json`, and on a name
collision the project entry wins. So a profile can **redefine** a server — point
`postgres` at a scratch database instead of production — but it cannot
**remove** one. Cursor documents disabling only as a toggle in the sidebar, with
no committable file behind it.

The practical answer is to keep the global file empty and let agentize render
`.cursor/mcp.json` per project. Then each project gets exactly what its profile
declares, and nothing else. Per-tool denies can go in `.cursor/cli.json`, which
does live in the repository.

Claude Code and Codex can subtract. OpenCode is rendered whole, so it is
already exact.

## Licence

MIT.
