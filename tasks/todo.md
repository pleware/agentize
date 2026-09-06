# agentize v0 — tasks

Plan and rationale: [`plan.md`](plan.md).

## Status

| Task | State |
| --- | --- |
| 1 Package, config loader, layout | done |
| 2 Layer resolver | done |
| 3 Cursor rules renderer | done |
| 4 `mount --check` | done |
| 5 AGENTS.md and OpenCode instructions | done |
| 6 MCP model and Cursor renderer | done |
| 7 Claude and Codex renderers | deferred past v0 |
| 8 OpenCode MCP renderer | done |
| 9 Profile resolution and git identity | done |
| 10 Launch with isolated host data | done for resolution — isolated copy by default, `--global` for PATH; Windows TUI spawn still not ported |
| 11 Project-owned skills | done |
| 12–15 Adoption | not started |

Task 10 has an open item in [`../backlog.md`](../backlog.md); fetching skills
from a remote repository is recorded there as a separate feature.

Standing verification for every task: `uv run ruff check .` and `uv run pytest`.
Source references point into the MassTrade repository, which is the origin of
the extracted code.

---

## Phase 1: Foundation

### Task 1: Package skeleton, config loader and layout

**Description:** Create an installable Python package with a `agentize` entry
point, and load `agentize.yaml` into typed objects. Reject an unknown `version`
loudly rather than guessing.

Policy is a root file beside `mani.yaml` and `ignite.toml`; `.agentize/` holds
runtime data only and ignores itself with `*`. This replaces the MassTrade
behaviour of appending entries to the project's root `.gitignore`, which is a
file agentize has no business editing.

**Acceptance criteria:**
- [ ] `uvx --from . agentize --version` prints a version
- [ ] The README's example config parses into objects without loss
- [ ] A config with `version: 2` fails with a message naming the supported version
- [ ] Creating `.agentize/` writes a `.gitignore` that hides the whole directory
- [ ] The project's root `.gitignore` is never modified
- [ ] A `.gitignore` that hides `agentize.yaml` is detected, and `init` reports the
      one-line whitelist that fixes it

**Verification:**
- [ ] Tests cover: valid config, missing file, unknown version, malformed YAML
- [ ] Test asserts that in a real temporary repository `agentize.yaml` is the only
      tracked file and nothing under `.agentize/` is staged
- [ ] `uv run ruff check .` clean

**Dependencies:** None

**Files likely touched:**
- `pyproject.toml`
- `src/agentize/__init__.py`, `src/agentize/cli.py`, `src/agentize/config.py`
- `src/agentize/store_tree.py`
- `tests/test_config.py`, `tests/test_store_tree.py`

**Estimated scope:** S

---

### Task 2: Layer resolver

**Description:** Implement `shared → hosts/<host> → profiles/<profile>` merging
as a pure function: given a config, a host, a profile and a listing of `.agents`,
return the ordered set of files to emit. No disk access inside the function.

**Acceptance criteria:**
- [ ] A file present in two layers resolves to the later layer, once
- [ ] Requesting an undeclared host or profile is an error, not an empty result
- [ ] The function is importable and callable with an in-memory file listing

**Verification:**
- [ ] Tests cover each layer alone, every overlap pair, and full three-layer override
- [ ] No test in this module touches the filesystem

**Dependencies:** Task 1

**Files likely touched:**
- `src/agentize/resolve.py`
- `tests/test_resolve.py`

**Estimated scope:** S

---

### Checkpoint: Foundation
- [ ] Resolver is pure and covered
- [ ] Config shape matches the README exactly — if it drifted, fix the README
- [ ] Human review before any renderer is written

---

## Phase 2: Mount (rules)

### Task 3: Cursor rules renderer

**Description:** Port `_sync_agents_mt` / `_sync_cursor_host` from
`mt-tools.py`. Emit resolved rules to `rules_dst` with `emit_prefix`, and delete
previously emitted files that are no longer resolved. Hand-written files without
the prefix are never touched.

**Acceptance criteria:**
- [ ] `agentize mount` writes `<prefix><name>.mdc` for every resolved rule
- [ ] Removing a source rule and re-running deletes the stale emitted file
- [ ] A hand-written `.mdc` without the prefix survives both runs
- [ ] Running twice with no changes produces no diff

**Verification:**
- [ ] Tests use a temporary directory and assert the full resulting file tree
- [ ] Manual: run against a copy of `.agents-mt` and diff against MassTrade's
      current `.cursor/rules` output — it should match

**Dependencies:** Task 2

**Files likely touched:**
- `src/agentize/hosts/cursor.py`
- `src/agentize/mount.py`
- `tests/test_mount_cursor.py`

**Estimated scope:** M

---

### Task 4: `mount --check`

**Description:** Add a mode that renders in memory, compares against what is on
disk, and exits non-zero on any difference without writing. This is the CI gate.

**Acceptance criteria:**
- [ ] Clean tree exits 0 and writes nothing
- [ ] Stale, missing or extra emitted file exits non-zero and names the paths
- [ ] `--check` never modifies the working tree, even partially

**Verification:**
- [ ] Test asserts file mtimes are unchanged after a failing `--check`

**Dependencies:** Task 3

**Files likely touched:**
- `src/agentize/mount.py`, `src/agentize/cli.py`
- `tests/test_mount_check.py`

**Estimated scope:** S

---

### Task 5: AGENTS.md and OpenCode instructions

**Description:** Emit the host-neutral `AGENTS.md` and the OpenCode
`instructions` list. `AGENTS.md` is read by every host, so it carries the shared
layer and needs no per-host dialect.

**Acceptance criteria:**
- [ ] Resolved shared rules appear in `AGENTS.md` in declared order
- [ ] OpenCode `instructions` globs resolve to the same content set
- [ ] Emitted content is delimited so hand-written prose above it survives

**Verification:**
- [ ] Test: hand-written preamble is preserved across two mounts

**Dependencies:** Task 3

**Files likely touched:**
- `src/agentize/hosts/opencode.py`, `src/agentize/hosts/agents_md.py`
- `tests/test_mount_agents_md.py`

**Estimated scope:** S

---

### Checkpoint: Mount
- [ ] `agentize mount` reproduces MassTrade's current rules output byte for byte
- [ ] `--check` is wired into this repository's own CI
- [ ] Human review

---

## Phase 3: MCP

### Task 6: MCP model and Cursor renderer

**Description:** Model MCP servers from config (stdio and remote variants) and
render `.cursor/mcp.json` containing exactly the servers the profile declares.
`${env:...}` values pass through untouched — agentize never resolves a secret.

**Acceptance criteria:**
- [ ] Only servers listed by the active profile appear in the output
- [ ] `${env:NAME}` survives verbatim into the rendered JSON
- [ ] A literal-looking secret in `env:` is rejected with an explanatory error
- [ ] Both stdio (`command`/`args`) and remote (`url`/`headers`) render correctly

**Verification:**
- [ ] Test asserts the `agent` profile's output omits `github` and `sentry`
- [ ] Manual: Cursor loads the rendered file and lists the expected servers

**Dependencies:** Task 2

**Files likely touched:**
- `src/agentize/mcp.py`, `src/agentize/hosts/cursor.py`
- `tests/test_mcp_cursor.py`

**Estimated scope:** M

---

### Task 7: Claude and Codex renderers — DEFERRED past v0

> **Not in v0.** Both hosts are `enabled: false` in the only real configuration
> we have, and a renderer with no consumer is untested code. Kept written so the
> work is ready when a project actually runs one of them. Do not start this
> without a consumer. Tracked in [`../backlog.md`](../backlog.md).

**Description:** Render `.mcp.json` for Claude Code and `.codex/config.toml` for
Codex, including the subtractive semantics each supports
(`disabledMcpjsonServers`, `enabled = false`).

**Acceptance criteria:**
- [ ] Claude output disables servers the profile excludes, rather than omitting them
- [ ] Codex TOML round-trips through a parser and matches the expected structure
- [ ] A host marked `enabled: false` produces no files at all

**Verification:**
- [ ] Tests parse the emitted TOML and JSON rather than comparing strings

**Dependencies:** Task 6

**Files likely touched:**
- `src/agentize/hosts/claude.py`, `src/agentize/hosts/codex.py`
- `tests/test_mcp_claude.py`, `tests/test_mcp_codex.py`

**Estimated scope:** M

---

### Task 8: OpenCode renderer

**Description:** Render the MCP block of `opencode.json`. OpenCode is written
whole, so the profile's server set is exact with no subtraction needed.

**Acceptance criteria:**
- [ ] Rendered file contains exactly the profile's servers
- [ ] Non-MCP keys already in `opencode.json` are preserved

**Verification:**
- [ ] Test: a hand-added unrelated key survives a mount

**Dependencies:** Task 6

**Files likely touched:**
- `src/agentize/hosts/opencode.py`
- `tests/test_mcp_opencode.py`

**Estimated scope:** S

---

### Checkpoint: MCP
- [ ] The `agent` profile demonstrably cannot reach the servers `human` can
- [ ] No secret value appears in any file under version control
- [ ] Human review

---

## Phase 4: Profiles and launch

### Task 9: Profile resolution and git identity

**Description:** Select the active profile (flag, then config default), and
expose its git identity as process environment (`GIT_AUTHOR_*`,
`GIT_COMMITTER_*`, push remote). Never run `git config --local`.

**Acceptance criteria:**
- [ ] `--profile agent` overrides the configured default
- [ ] Identity is applied to the child process only; the repository config is untouched
- [ ] A profile without a `git` block inherits the machine identity unchanged

**Verification:**
- [ ] Test asserts `.git/config` is byte-identical before and after
- [ ] Manual: a commit made under `agent` carries the bot's name

**Dependencies:** Task 2

**Files likely touched:**
- `src/agentize/profile.py`, `src/agentize/gitenv.py`
- `tests/test_profile.py`

**Estimated scope:** M

---

### Task 10: Launch with isolated host data

**Description:** Port the launcher from `agentize.py`: spawn the host with the
profile's environment and, when `isolate_data` is set, a private data directory
under `.agentize/<host>/`. Port the Windows spawn helpers as they are.

**Acceptance criteria:**
- [ ] `agentize` launches the default profile's host and returns its exit code
- [ ] `isolate_data: true` yields a per-project database, not the user's global one
- [ ] Windows console handling matches current behaviour

**Verification:**
- [ ] Manual on Windows and Linux — this is an edge, so it is checked by hand
- [ ] Test covers argv and environment construction without spawning

**Dependencies:** Task 9

**Files likely touched:**
- `src/agentize/launch.py`, `src/agentize/hosts/*.py`
- `tests/test_launch_argv.py`

**Estimated scope:** M

---

### Task 11: Project-owned skills

**Description:** Emit the skills a project authors, resolved through the same
layers as rules, into each host's own skills directory. The directory holding
`SKILL.md` is the unit, so a layer wins a whole skill rather than single files.

Fetching skills from a remote repository is **not** in scope — see "Vendored
skills" in [`../backlog.md`](../backlog.md) for why that turned out to be a
separate feature rather than the other half of this one.

**Acceptance criteria:**
- [x] Skills land where only the target host reads them, and never in a directory
      several hosts scan in common
- [x] A profile's `skills` list narrows the set; omitting it emits everything
- [x] A profile naming a skill no layer provides fails with a message
- [x] Pruning removes only prefixed directories; a hand-written skill survives
- [x] The whole skill directory is copied, not just `SKILL.md` — MassTrade copies
      only the marker file, which silently drops helper files

**Verification:**
- [x] Tests cover layering, selection, pruning, collision and idempotency
- [x] `uv run ruff check .` clean

**Dependencies:** Task 9

**Files likely touched:**
- `src/agentize/skills.py`, `src/agentize/mount.py`
- `src/agentize/hosts/cursor.py`, `src/agentize/hosts/opencode.py`
- `tests/test_skills.py`

**Estimated scope:** M

---

### Checkpoint: Profiles and launch
- [ ] Two profiles launch the same project with visibly different capability
- [ ] Human review before touching any consumer repository

---

## Phase 5: Adoption

### Task 12: Publish to PyPI

**Description:** Package metadata, licence, and a release workflow so
`uvx agentize` works from a clean machine. Resolve the name question first.

**Acceptance criteria:**
- [ ] `uvx agentize --version` works on a machine that has never seen the source
- [ ] Tagged release publishes; untagged pushes do not
- [ ] README renders correctly on the package page

**Verification:**
- [ ] Install from the index in a clean container and run `mount --check`

**Dependencies:** Task 11

**Files likely touched:**
- `pyproject.toml`, `.github/workflows/release.yml`

**Estimated scope:** S

---

Full migration is too large for one task, so it lands in two: rules first, then
skills and launch. Each leaves MassTrade in a working state.

### Task 13: MassTrade migrates rules and MCP

**Description:** Convert `.agents-mt/hosts.json` to `agentize.yaml` and split rules that are really about the *bot* into `profiles/agent/`. Delete the
mount code from `mt-tools.py` in the same change — never run both mounts.

LiteLLM config sync stays in `mt-tools`, untouched. It configures an externally
hosted proxy and is not agentize's concern.

**Acceptance criteria:**
- [ ] `agentize mount` produces the same `.cursor/rules` output as mt-tools did
- [ ] Mount code is gone from `mt-tools.py` — not left dormant behind a flag
- [ ] Rules that say "push to the bot's remote" live under the profile, not the host
- [ ] LiteLLM sync still works, unchanged by this task

**Verification:**
- [ ] Diff the emitted tree before and after: it should be empty
- [ ] MassTrade's pipeline stays green (Bitbucket — read the failed logs, per `ci-logs`)

**Dependencies:** Task 12

**Files likely touched:** MassTrade repository (separate remote, separate commit)

**Estimated scope:** M

---

### Task 14: MassTrade migrates skills and launch

**Description:** Move skill installation and the OpenCode launcher onto the
public tool, then delete `setup_dev/agent_skills.py` and
`scripts/development/agentize/`. Resolve the OMO question in
[`../backlog.md`](../backlog.md) before starting — it decides where that
templating lands.

**Acceptance criteria:**
- [ ] Skills land in OpenCode's private directory and do not leak into Cursor's
- [ ] Both private implementations are deleted, not disabled
- [ ] Launch still produces bot-attributed commits and an isolated database
- [ ] OMO templating works, wherever the backlog decision put it
- [ ] The `# agentize workspace (MassTrade)` block is removed from MassTrade's
      root `.gitignore`, leaving one `!/agentize.yaml` whitelist line

**Verification:**
- [ ] Manual on Windows: junctions are removed as entries, not followed
- [ ] Existing `test_agent_skills.py` cases pass against the public implementation

**Dependencies:** Task 13

**Files likely touched:** MassTrade repository (separate remote, separate commit)

**Estimated scope:** M

---

### Task 15: initagent adopts

**Description:** Add agentize to `initagent-workspace` as the second consumer.
The first consumer proves the extraction; the second proves it generalized.

**Acceptance criteria:**
- [ ] A config written without reference to MassTrade produces working output
- [ ] `mount --check` runs in that repository's CI
- [ ] Anything that had to be special-cased is recorded as a defect, not a workaround

**Verification:**
- [ ] GitHub Actions run is green — read the logs, do not assume

**Dependencies:** Task 14

**Files likely touched:** `initagent-workspace` (separate remote, separate commit)

**Estimated scope:** S

---

## Checkpoint: Complete
- [ ] Two independent projects consume the same tool
- [ ] No mount logic remains in any private copy
- [ ] The README's "does not do" table is still true
