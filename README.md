# agentize

One project config. Every agent host.

> **Status: design.** Nothing is implemented yet. This README describes the
> shape that was locked before writing code, so the scope stays honest.

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
agentize                 # launch a host with a profile applied
agentize mount           # render rules, skills and MCP config for each host
agentize mount --check   # CI gate: fail if the rendered output is stale
```

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
```

Not a matrix. Two profiles and four hosts would be eight combinations, six of
them empty.

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

A profile can narrow the set:

```yaml
profiles:
  agent:
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
    emit_prefix: auto.
  opencode:
    addons: [omo]
  claude: { enabled: false }
  codex:  { enabled: false }

profiles:
  human:
    default: true
    # No git block: a human's identity differs per teammate.
    # It comes from the machine file, not the repository.
    mcp: [postgres, github, sentry]
    skills: [code-review, idea-refine]

  agent:
    git:                          # one bot, shared by the team → belongs here
      user_name: acme-agent
      user_email: agent@example.com
      push_remote: bot
    isolate_data: true
    mcp: [postgres]               # no issue tracker, no deploy tooling
    skills: [code-review]

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

### Layout

```
<project>/
  agentize.yaml        policy — commit this
  .agentize/           runtime data — ignores itself
    local.yaml         per-clone override
    opencode/          host data
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
| Agent authorization       | The MCP spec is standardizing agent identity    |
| Toolchain installation    | That is a workspace bootstrapper's job          |
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
