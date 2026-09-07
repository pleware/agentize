# agentize

[![CI](https://github.com/pleware/agentize/actions/workflows/ci.yml/badge.svg)](https://github.com/pleware/agentize/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/pleware/agentize/branch/main/graph/badge.svg)](https://codecov.io/gh/pleware/agentize)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-lightgrey?style=flat-square)](LICENSE)

One project config. Every agent host.

<small>Status: Cursor and OpenCode work. Claude Code and Codex are deferred. <code>run</code> starts the project's isolated copy of a host, not whatever happens to be on <code>PATH</code>. Both hosts track <code>latest</code> and update themselves after the first <code>fetch</code>. <code>run --agent</code> also plants <a href="https://github.com/pleware/ignite">ignite</a> and installs that slug's <code>needs</code> from <code>mise.toml</code>.</small>

## Install

Run the matching one-liner in the project root. That is the whole install.

### Linux

```sh
curl -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.sh | sh
```

### macOS

```sh
curl -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install-macos.sh | sh
```

### Windows

```cmd
cmd /c "curl.exe -fsSL https://raw.githubusercontent.com/pleware/agentize/main/scripts/install.ps1 -o %TEMP%\agentize-install.ps1 && powershell -NoProfile -ExecutionPolicy Bypass -File %TEMP%\agentize-install.ps1"
```

<small>Note: one line on purpose. Command Prompt has no <code>iex</code>, and PowerShell turns <code>curl.exe</code> output into an array that <code>iex</code> will not accept. This downloads with <code>curl.exe</code> (so WinINET cannot serve a stale <code>irm</code> copy) and runs the script as a file. After that, <code>.\agentize fetch</code> works in both shells.</small>

### After install

Add `agentize.yaml` (and, for bots, `ignite.toml` + `mise.toml`) and run `./agentize fetch` (Windows: `.\agentize fetch`).

<small>If <code>uv</code> / <code>uvx</code> is missing, the script downloads the current GitHub release, checks the <code>.sha256</code> sidecar, and puts both binaries in <code>~/.local/bin</code> (and on your user PATH on Windows). Then it downloads the three launchers and checks those hashes against <code>scripts/checksums.txt</code>. A failed hash writes nothing. The files it writes (<code>agentize</code>, <code>agentize.ps1</code>, <code>agentize.cmd</code>) are trampolines, not the package. They call <code>uvx --refresh --from git+https://github.com/pleware/agentize.git</code>.</small>

## Commands

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

<small>See <a href="#toolchain">Toolchain</a> for <code>ignite.toml</code>, <code>needs</code>, and where the kit lands.</small>

### Cascade

`mount` at a directory that has `mani.yaml` always walks that registry and
plants inherited Cursor MCP into every existing child (then each child's own
`mani.yaml`). No `--cascade` flag.

A child listed in `mani.yaml` does not need `agentize.yaml`. Membership plus
an observed parent is enough. Child policy merges on top (child wins).
`inherit: []` or `inherit: false` refuses. `inherit: [mcp]` keeps only that
channel.

Relative `--directory`, `-C`, and `--project` are resolved from the
`agentize.yaml` that **declared** the server, then rewritten to the plant
cwd. A binder `mount` does not treat a child's command as if it lived on
the binder. An inherited server still rebases from the parent yaml (so
`uv run --directory family/orchestrator` becomes `../family/orchestrator`
inside a product folder).

Cascade writes only `.cursor/mcp.json` and `.agentize/parents.yaml`. It never
plants `AGENTS.md`. Missing child paths are a skip. Scope is the `mani.yaml`
you started in — MassTrade Atlassian does not leak into the binder.

A binder with an empty `mcp:` list does not write an empty project
`mcp.json` onto a child that has no `agentize.yaml`.

`${marker:rel}` in planted MCP `env` walks that same `mani.yaml` tree
(binder → workspace → product). It does not look up a product folder name.
An unresolved marker is dropped so runtime discovery can still find the tree.

### User MCP (`agentize-*`)

Cursor's Customize → MCPs tab often hides project servers in a multi-root
`.code-workspace`. `mount` also writes the planted human servers into
`~/.cursor/mcp.json`, each renamed `agentize-<name>`, with absolute
`--directory` paths. Only those prefixed keys are owned. Wren and the rest
of the user file stay. `hosts.cursor.user_mcp: false` turns this off.
`cleanup --home` removes the prefix keys.

Last `mount` wins if two trees disagree. Two Cursor windows share one user
file.

### Launchers

`agentize init` plants three launchers (`agentize`, `agentize.ps1`, `agentize.cmd`) next to `agentize.yaml`. They are not the package.

<small>They call <code>uvx --refresh --from git+https://github.com/pleware/agentize.git</code>, so a week-old clone still starts today's build. <code>AGENTIZE_OFFLINE=1</code> skips the check and uses the cache. Inside this repository the same files call <code>uv run</code> instead, so development does not go through GitHub.</small>

### Cleanup

`agentize cleanup` (or `--cleanup`) is the inverse of `init`.

<small>It deletes <code>.agentize/</code> and any launcher whose bytes still match the planted trampoline. A hand-edited launcher stays. <code>agentize.yaml</code> stays. Files <code>mount</code> wrote (<code>.cursor/</code>, <code>opencode.json</code>, <code>tui.json</code>, <code>AGENTS.md</code>) stay. <code>--home</code> also deletes <code>~/.agentize/</code> (<code>$AGENTIZE_HOME</code> if set). <code>--check</code> reports without deleting.</small>

### Isolated hosts

`cursor` here is the **agent CLI** (`agent` / `cursor-agent`), not the desktop editor.

<small><code>run</code> never copies a shim from <code>PATH</code>. A missing copy is an error that names <code>agentize fetch</code>. After that first copy, leave the binary alone: Cursor Agent (<code>agent update</code>) and OpenCode refresh themselves in the same tree. The last host, profile and agent slug are stored in <code>.agentize/last.yaml</code> (and a copy under <code>~/.agentize/</code>). That is why a bare <code>agentize</code> is enough the second time — and why it still works in a directory that has no <code>agentize.yaml</code> yet. The committed file is never rewritten on launch.</small>

## Why

### The problem

You wire up an MCP server in Cursor. Then again in Claude Code. Then again in Codex, in TOML this time. The rules that explain how your repository works get copy-pasted between hosts and quietly drift apart.

Then there is the part nobody configures at all:

**Your agent and you are not the same user.**

The agent commits under your name, or you scrub the attribution afterwards. It loads the same MCP servers you do, including the one wired to a production database. It gets your issue-tracker credentials, because nothing ever said it should not.

Most setups cannot express *"the bot gets less than the human"* — the config has only one axis: which host.

### What agentize adds

You declare **who** (profile or agent slug) and **where** (host) once, and it renders the native config each host expects.

<small>On <code>run --agent</code> it also makes sure the machine has the toolchain that slug named — by calling ignite, not by downloading PHP itself.</small>

### Two axes

|            | `cursor` | `opencode` | `claude` | `codex` |
| ---------- | -------- | ---------- | -------- | ------- |
| **human**  | ✓        |            |          |         |
| **agent**  |          | ✓          |          | ✓       |

A **host** is the program. A **profile** is who is driving it. They are independent: an agent can run in Cursor, a human can run in Codex.

<small>Today these get conflated. A file called "OpenCode rules" ends up containing <i>always push to the bot's remote</i> — which is a rule about the <b>bot</b>, not about <b>OpenCode</b>. It works only until the first human opens that host.</small>

## Layering

Content composes in three layers. Later wins.

```
shared  →  hosts/<host>  →  profiles/<profile>
shared  →  hosts/<host>  →  agents/default  →  agents/<slug>
```

### Profiles and slugs

A **profile** is who is driving (a human, today). An **agent slug** is which bot (`php`, `go`, `docs`). `agents.default` is the shared bot base; a slug overrides only the keys it sets.

<small><code>needs</code> is the mise tool list for that slug (<code>php@7.4</code> during a migration). Versions stay in <code>mise.toml</code>. Not a matrix of host × slug.</small>

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

A skill layers like everything else, with one difference: the **directory** is the unit. The winning layer supplies the whole skill, never a mixture.

Each host receives its own copy, in a directory only that host reads: `.cursor/skills` and `.opencode/skills`.

<small>A <code>SKILL.md</code> from one layer describing helper files from another is not a skill anybody wrote. agentize never writes into <code>.agents/skills</code>, <code>.claude/skills</code> or <code>.codex/skills</code>, which several hosts scan in common — so a skill intended for one host cannot be picked up by another, and there is nothing to clean up after the fact. agentize copies skills the project already owns. It does not fetch them — <code>npx skills</code> and the host marketplaces do that.</small>

A profile or agent slug can narrow the set:

```yaml
agents:
  default:
    skills: [review]     # omit the key to get every skill the layers resolve
```

## Configuration

### Example

```yaml
# agentize.yaml
version: 1

source: .agents

hosts:
  cursor:
    emit_prefix: auto.
    pin: latest                 # or omit; Cursor Agent updates itself
  opencode:
    default: true               # bare `agentize` starts this until last.yaml remembers
    pin: latest                 # or omit; OpenCode updates itself
    plugins:
      - opencode-extended-sidebar  # TUI sidebar; omitted plugins default to this
      - oh-my-openagent            # server plugin; OpenCode installs both at startup
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

<small>Secrets are never written into a project file. <code>${env:...}</code> is a reference; values are injected into the host process at launch, from a machine-level file outside the repository. Git identity is set as process environment. agentize never runs <code>git config --local</code>. YAML for the source because it nests and takes comments. The output formats are not a choice — each host dictates its own.</small>

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

~/.agentize/           # or $AGENTIZE_HOME — machine, not the project
  last.yaml
  ignite/<pin>/        planted ignite kit (`ensure.sh`); shared by checkouts
```

Policy is one file at the project root, beside `mani.yaml` and `ignite.toml`.

### Hosts and versions

`pin: latest` (or omitting `pin`) is the default for Cursor Agent and OpenCode. Both programs update themselves.

<small>agentize installs them once into <code>.agentize/hosts/&lt;name&gt;/versions/latest/</code> and does not fight a later overwrite. <code>agentize fetch</code> is that first copy. If the <code>latest</code> tree already looks installed, fetch leaves it alone so a self-update is not replaced by an older archive. A numbered pin still skips when that exact version is already present. Cursor has no <code>/latest/</code> download URL. The first fetch reads today's build id from <code>https://cursor.com/install</code>, then unpacks that archive into <code>latest</code>. OpenCode uses GitHub's <code>releases/latest</code> redirect. A concrete pin (<code>pin: "1.18.4"</code> or <code>pin: "2026.09.02-c22c1a3"</code>) is the escape hatch: fetch that tag, and <code>run</code> refuses if the <code>current</code> pointer does not match.</small>

### Plugins

OpenCode plugins are a list on the host, not a profile.

- TUI packages (`opencode-extended-sidebar`; `oes` is an alias) go into `tui.json`.
- Server packages such as [Oh My OpenAgent](https://github.com/code-yeongyu/oh-my-openagent) (`oh-my-openagent`; `omo` is an alias) stay on `opencode.json` as `plugin`.

<small>Omitting <code>plugins</code> on OpenCode defaults to the sidebar. An empty list means none. OpenCode installs the npm packages itself at startup — agentize does not.</small>

## Toolchain

A bot on a cold machine still has to compile PHP. agentize does not plant compilers. It requires [ignite](https://github.com/pleware/ignite) and asks ignite to install the mise tools the slug listed.

### Policy files

Committed next to `agentize.yaml`:

```toml
# ignite.toml
[kit]
pin = "fee062f"   # a commit that has ensure.sh — not main on a fleet
```

```toml
# mise.toml — versions live here, not in agentize.yaml
[tools]
"php@7.4" = "7.4.33"
"php@8.3" = "8.3.6"
```

```yaml
agents:
  default:
    needs: [php@8.3]
  php:
    needs: [php@8.3, phpantom]
  php74:
    needs: [php@7.4]
```

### What `run --agent` does

`run --agent php` then:

1. Reads `[kit] pin` from `ignite.toml` (missing file or missing pin is an error).
2. Clones that ref into `~/.agentize/ignite/<pin>/` if `ensure.sh` is not there.
3. Runs `ensure.sh <project> php@8.3 phpantom` — mise only, no `mani.yaml` clones.
4. Puts mise shims on `PATH`, mounts, starts the host.

<small><code>--profile human</code> skips all of that. <code>mount</code> only renders files; it does not install tools. Two PHP versions in one checkout are two slugs and two pins in <code>mise.toml</code>.</small>

## Host support

| | Cursor | Claude Code | Codex | OpenCode |
| --- | --- | --- | --- | --- |
| Project MCP file | `.cursor/mcp.json` | `.mcp.json` | `.codex/config.toml` | `opencode.json` |
| TUI plugins | — | — | — | `tui.json` |
| Format | JSON | JSON | TOML | JSON |
| Disable one server | UI toggle only | `disabledMcpjsonServers` | `enabled = false` | rendered whole |
| Tool allowlist | `.cursor/cli.json` | permission rules | `enabled_tools` | — |
| Env interpolation | `${env:...}` | — | `env:VAR` | — |
| Native profiles | no | no | **yes** | no |

<small>Codex already has profiles. agentize generalizes that model to the hosts that do not.</small>

### Cursor limitation

Cursor merges `~/.cursor/mcp.json` with `.cursor/mcp.json`, and on a name collision the project entry wins. A profile can **redefine** a server, but it cannot **remove** one.

<small>Cursor documents disabling only as a toggle in the sidebar, with no committable file behind it. The practical answer is to keep the global file empty and let agentize render <code>.cursor/mcp.json</code> per project. Then each project gets exactly what its profile declares, and nothing else. Per-tool denies can go in <code>.cursor/cli.json</code>, which does live in the repository. Claude Code and Codex can subtract. OpenCode is rendered whole, so it is already exact.</small>

### Out of scope

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

<small>What is left is narrow: one source, four dialects, plus the profile axis for the hosts that lack it.</small>

## Gitignore

A deny-by-default `.gitignore` needs the launchers and the policy file whitelisted:

```gitignore
!/agentize
!/agentize.ps1
!/agentize.cmd
!/agentize.yaml
```

<small><code>.agentize/</code> holds only machine state, so it ignores itself with a <code>.gitignore</code> containing <code>*</code> — the same trick <code>uv</code> uses for <code>.venv</code>. Your project needs no rule for it, and agentize never edits a <code>.gitignore</code> the project owns. <code>agentize init</code> refuses to continue when <code>agentize.yaml</code> sits behind an ignore rule, because a policy nobody can commit is worse than no policy at all.</small>

## Licence

MIT.
