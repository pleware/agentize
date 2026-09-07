# Backlog

Open questions and unfinished thinking. Not tasks — see [`tasks/todo.md`](tasks/todo.md)
for work that is ready to start. An item leaves this file either by becoming a
task or by being answered in the README.

## Blocking a decision already made

### OMO templating — does it follow MassTrade into agentize?

MassTrade renders `.omo/omo.jsonc` from a source template on every run. Now that
MassTrade migrates fully, that rendering has to go somewhere.

Three shapes, none chosen:

- **A host addon.** `hosts.opencode.plugins` now lists npm specs (default
  `opencode-extended-sidebar` in `tui.json`; `oh-my-openagent` stays a server
  entry on `opencode.json`). That is the plugin *entry*. Rendering
  `.omo/omo.jsonc` from a template is still open.
- **A generic "render this template" hook.** agentize stays ignorant of OMO;
  the project declares a source and a destination.
- **Stays in MassTrade.** A small script keeps rendering it, outside agentize.

The first makes agentize know about a third-party OpenCode plugin. The second
risks turning agentize into a template engine, which is a different product.
Decide before Task 13.

## Unfinished implementation

### Windows console handling for the OpenCode TUI

`launch.py` spawns the host directly with `subprocess.run`. MassTrade's
implementation does considerably more on Windows: from Windows Terminal it
starts pwsh, and from a plain console it relaunches through `wt`, passing a
base64-encoded command. That machinery exists because the OpenCode TUI
misbehaves in `conhost`.

It was not ported, deliberately: roughly 150 lines of console handling that
cannot be verified without OpenCode installed, and unverifiable ported code is
worse than an honest gap. The source is `scripts/development/agentize/agentize.py`
in MassTrade — `_pwsh_tui_argv`, `_opencode_pwsh_command`, `_pwsh_encoded_command`,
`_opencode_spawn_argv`, `_spawn_opencode`.

Do this before Task 14, on a machine where the result can actually be run.

### Cursor Agent auto-update vs a pin

`fetch` installs a versioned tree under `.agentize/hosts/cursor/versions/<pin>/`.
The official CLI likes to update itself. If that write lands inside our tree,
the pin in `agentize.yaml` becomes a lie. Either find the env/flag that
disables auto-update and set it in `launch_env`, or treat `versions/<pin>/` as
read-only for `run` and only `fetch` may replace it. Unverified.

### Vendored skills — fetching from a remote repository

Not in v0, and deliberately not called "skills" any more, because two unrelated
features were sharing that word.

What v0 does: copy skills the project owns, resolved through the same layers as
rules. What it does not: fetch a skill from GitHub. MassTrade has code for that
(`agent_skills.py` — `npx skills add` into an isolated staging repository, then
a move into `~/.config/opencode/skills`, then pruning copies out of every shared
directory), driven by `opencode.skills_sources` in `hosts.json`.

Two things make it a poor fit for v0:

- **It is configured off.** The real `hosts.json` has no `skills_sources` key,
  and the installer prints "nothing to do". The one entry in
  `skills-lock.json` (`wren`) came from running the CLI by hand.
- **Most of it exists to undo a mistake.** The pruning machinery is there
  because `npx skills -a opencode` writes into `.agents/skills`, which Cursor
  also reads. agentize writes straight into `.opencode/skills`, so the leak it
  cleans up never happens.

If a consumer asks for this, the open question is whether agentize shells out to
`npx skills` at all, or simply documents that the CLI owns fetching and agentize
owns placement.

## Undecided design

### Are rendered host files committed or ignored?

`mount` writes `.cursor/rules/auto.*.mdc`, `.cursor/mcp.json` and
`opencode.json`. Nothing has decided whether those belong in version control.

The two positions pull in opposite directions:

- **Committed.** The team gets identical rules and identical MCP servers from a
  clone, and `mount --check` has something to check — a CI gate over files
  nobody tracks is meaningless. Cursor's own documentation says to commit
  `.cursor/mcp.json` "so teammates get the same tools".
- **Ignored.** Every repository we audited already ignores `opencode.json`, on
  the reasoning that it is generated and can carry machine-specific values.

An audit of our repositories showed the current state is inconsistent: MassTrade
tracks emitted `.cursor/rules/auto.mt.*.mdc` but ignores `opencode.json`. So
today rules are committed and host config is not, without that ever being a
decision.

Blocks nothing yet. It blocks Task 13, because migrating MassTrade means picking
one.

### `.agents/` is both our source and someone else's install target

agentize reads rules from `.agents/`. The `skills` CLI *writes* into
`.agents/skills/`. Those are not the same kind of directory, and the collision
is already visible in our own repositories:

- `opencode-extended-sidebar` ignores `.agents/` outright — for it, the
  directory is tool output, because `npx skills` installs there.
- `initagent-workspace` and both umbrellas track `.agents/skills/**` — for them
  it is authored source.
- MassTrade sidesteps the whole thing by naming its source `.agents-mt/`.

If agentize keeps `.agents/` as the source, adopting it in a repository that
ignores that path silently drops every rule. Either pick a name that cannot
collide (as MassTrade did), or make the source directory configurable and
default to something unambiguous.

Narrower than it was: agentize now writes skills into `.cursor/skills` and
`.opencode/skills` and never into `.agents/skills`, so the two tools no longer
write to the same place. What remains is the reading half — a repository that
ignores `.agents/` because a CLI installs there will also hide the rules it
authored.

### Where the machine-level secret file lives

The README promises `${env:...}` values are "injected into the host process at
launch, from a machine-level file outside the repository." That file has no
path, no format and no precedence rule yet. Needed before Task 10.

### How hooks read the profile

The README says agentize does not install git hooks, it "only exposes the
profile hooks read." The exposure mechanism is unspecified — an environment
variable, a file under `.agentize/`, or a `agentize profile --name` query a
hook can call. The third is the least fragile but adds a startup cost to every
hook invocation.

### What `skills.lock` actually is

Answered enough to drop from the README, not enough to implement. `skills-lock.json`
is written by `npx skills` and records a remote source and a content hash, so it
belongs to vendored skills above, not to the ones a project writes itself —
those are already versioned by the repository holding them.

`config.py` still parses a `skills.lock` key so an existing file does not break
loading, but nothing reads the result. Either wire it up with vendored skills or
remove the field.

### Worktrees

`.agentize_worktrees` is carried over from the MassTrade implementation. No
consumer has asked for it in the public tool. Either find the use case or drop
it from the config before v0 freezes the shape.

## Deferred

### Claude Code and Codex renderers

Deferred past v0 — both are `enabled: false` in the only real configuration we
have, and a renderer with no consumer is untested code. Task 7 in `todo.md`
stays written so the work is ready when a consumer appears.

Three options were on the table. Recording all of them, because the reasoning
matters more than the verdict when this is picked up again:

- **Defer both — chosen.** Ship Cursor and OpenCode, which have real users. The
  cost is that the README promises four hosts while v0 delivers two, so the
  README has to say so plainly rather than imply the rest already work.
- **Build both now.** Four hosts is the headline promise, and the argument is
  that a config format proves itself only against dialects that disagree. The
  objection stands: two of those renderers would ship green and unexercised, and
  the first real user would be the one finding the bugs.
- **Codex only.** The interesting one. Codex is the sole host with **native
  profiles**, so its renderer is the only place our profile model can be checked
  against somebody else's implementation of the same idea. That is design
  validation, not just coverage — and it is a reason to build a renderer even
  without a user.

Revisit when: a project actually runs one of them, or the profile model starts
feeling speculative and Codex becomes worth building as a cross-check.

### LiteLLM config sync

Dropped, not deferred. MassTrade's `mt-tools` syncs a LiteLLM `config.yaml` from
its model registry. That is server-side configuration for an externally hosted
proxy — it has nothing to do with bootstrapping an agent host, and per the
workspace architecture rules LiteLLM is not ours to plant. It does not move into
agentize and it does not block Task 13.

## Unverified external behaviour

### Cursor's `"disabled": true`

Community threads report a `disabled` field in `mcp.json`. Official Cursor
documentation does not mention it. We do not build on it. If it turns out to be
real and stable, it simplifies profile isolation in Cursor considerably — worth
re-checking when Cursor's MCP docs change.

### Where Cursor stores MCP toggle state

Undocumented. If it turns out to be a committable file, a profile could subtract
a server in Cursor after all, and the README's limitation section needs
rewriting.

## Housekeeping

### PyPI name

Is `agentize` available? If not, the package name and the CLI name diverge,
which changes install instructions everywhere. Check before Task 12, not during.
