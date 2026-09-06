# Implementation Plan: agentize v0

## Overview

agentize is not a new idea — it is an extraction. Working code already exists
inside the MassTrade repository, spread across three places, hardcoded to one
company. This plan pulls that machinery into a public tool, adds the profile
axis, and adds MCP rendering (the one part that does not exist anywhere yet).

The proof of success is not "the tests pass". It is MassTrade deleting its
private copy and consuming the public tool instead.

## What already exists

| Capability | Lives in | Size |
| --- | --- | --- |
| Mount rules → `.cursor/rules`, OpenCode instructions | `scripts/development/tools/mt-tools/mt-tools.py` (`_sync_agents_mt`, `_sync_cursor_host`) | ~100 lines |
| Install skills into OpenCode's private dir, prune leaks | `scripts/development/tools/src/setup_dev/agent_skills.py` | 225 lines |
| `.agentize/config.yaml`, git identity, worktrees, gitignore, isolated data, launch | `scripts/development/agentize/agentize.py` | 1164 lines |
| Host manifest (`rules_src`, `rules_dst`, `emit_prefix`, `instructions`) | `.agents-mt/hosts.json` | 28 lines |

`agentize.py` matches MassTrade-specific strings 155 times. The extraction is
real work, not a file copy.

**Nothing today renders MCP configuration.** `opencode.json` is generated from a
model registry, and `.agents-mt/shared/mcp/*.mdc` are prose *about* MCP. Phase 3
is a genuine build, not a port.

## Architecture Decisions

**Python.** The code being extracted is Python, and `mise` already pins `uv` in
every product. `uvx agentize` needs no new toolchain. A rewrite in Go would buy
a single binary and cost the entire head start.

**Depend on PyYAML.** The MassTrade code hand-rolls a YAML scalar reader
(`_read_nested_yaml_scalar`) to avoid a dependency inside a constrained
toolchain. A public tool has no such excuse, and the config in the README nests
deeper than a line-scanner can survive. Per `open-source-first`: use the library.

**Resolution is a pure function.** Layer merging takes a config plus a file
listing and returns the set of files to emit. No disk, no network. Filesystem
writes sit at one thin edge. Per `try-testable`.

**Toolchain commands stay behind.** `agentize env`, `exec`, `verify` and
`upgrade` exist in the MassTrade script but belong to a workspace bootstrapper,
not here. The README already promises agentize does not install toolchains;
porting those commands would break that promise on day one.

**MassTrade migrates fully.** Not a shim. The public tool owns mount, MCP,
profiles, skills and launch, and MassTrade's private copies are deleted. Two
carve-outs: LiteLLM config sync is dropped entirely (it configures an externally
hosted proxy, not an agent host), and OMO templating is unresolved — see
`backlog.md` before starting Task 13.

**v0 ships two hosts.** Cursor and OpenCode, because both have real consumers.
Claude Code and Codex are deferred; a renderer nobody runs is untested code
wearing a green checkmark.

**Policy at the root, data in `.agentize/`.** The same split ignite settled on:
`ignite.toml` beside `.ignite/`, so `agentize.yaml` beside `.agentize/`. A
committed file sits where a reader already looks for `mani.yaml`, and a
whitelist repository names it in one line instead of un-ignoring a directory.
The data directory ignores itself with `*`, so no consumer needs gitignore
instructions and agentize never edits a file the project owns — which is what
MassTrade's version does today, appending to the root `.gitignore` behind a
marker comment.

**Mount is idempotent and prunable.** Emitted files carry a prefix
(`emit_prefix`) so a second run can delete what it previously wrote without
touching hand-written files. This is the existing MassTrade behaviour and it is
correct — keep it.

## Dependency graph

```
config loader (T1)
  └── layer resolver (T2)          ← the heart; pure, heavily tested
        ├── rules mount (T3, T4, T5)
        ├── MCP render (T6, T7, T8)
        └── profiles (T9)
              ├── launch (T10)
              └── skills (T11)
                    └── adoption (T12 → T13 → T14 → T15)
```

## Task List

Tasks live in [`todo.md`](todo.md).

### Phase 1: Foundation
- Task 1: Package skeleton and config loader
- Task 2: Layer resolver

### Phase 2: Mount (rules)
- Task 3: Cursor rules renderer
- Task 4: `mount --check`
- Task 5: AGENTS.md and OpenCode instructions

### Phase 3: MCP
- Task 6: MCP model and Cursor renderer
- Task 7: Claude and Codex renderers — **deferred past v0**
- Task 8: OpenCode renderer

### Phase 4: Profiles and launch
- Task 9: Profile resolution and git identity
- Task 10: Launch with isolated host data
- Task 11: Skills installation

### Phase 5: Adoption
- Task 12: Publish to PyPI
- Task 13: MassTrade migrates rules and MCP
- Task 14: MassTrade migrates skills and launch
- Task 15: initagent adopts

## Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Windows behaviour is hard-won (junctions, pwsh spawn, UTF-8, `npx.cmd`) and easy to lose in a port | High | Port those helpers verbatim where they are already correct; do not "clean them up" during extraction |
| Two owners of mount during migration — mt-tools and agentize both writing `.cursor/rules` | High | Task 13 removes the mt-tools path in the same change that enables agentize. Never run both |
| Cursor cannot remove an inherited global MCP server | Medium | Documented in README. Strategy is empty global file plus per-project render; `.cursor/cli.json` for per-tool denies |
| MassTrade coupling runs deeper than 155 string matches suggest | Medium | Phase 5 is last on purpose. Phases 1–4 build against the public config shape, not against MassTrade |
| Scope creep back into toolchain territory | Medium | The README's "does not do" table is the contract. Adding `agentize install` means the README was wrong — change it deliberately or not at all |

## Open Questions

Tracked in [`../backlog.md`](../backlog.md). The largest one still open is OMO
templating, which blocks Task 13. Three more block earlier tasks: where the
machine-level secret file lives (Task 10), how hooks read the active profile,
and what `skills-lock.json` is relative to the `npx skills` lockfile (Task 11).
