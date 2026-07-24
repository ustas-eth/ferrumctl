# AGENTS

`ferrumctl` is a small suite of host tools for Codex power users. The packages
should feel like ordinary Unix commands: narrow purpose, predictable output,
clear exit status, and easy composition with shell tools.

## Design Posture

Prefer boring primitives over orchestration frameworks. A command should expose
one useful operation on one state surface; workflows belong in docs, skills, or
the caller's script.

A read-only orientation command may combine observations when that avoids
guesswork, but it must preserve each source's label and freshness. Mutating
commands should remain bound to one state surface.

Keep the CLI layer neutral. Skills may recommend an opinionated Codex workflow,
but the binaries should remain useful when installed and used separately.

Avoid convenience abstractions until the repeated use case is obvious. Do not
introduce a suite wrapper, shared daemon, or common library just to make the
repo look unified. A cross-package dependency must represent a real behavioral
layer; wakectl depends on threadctl's client because deferred delivery must use
the same turn-scoped app-server operations as immediate control.

## System Boundaries

The tools touch several independent Codex surfaces:

- live app-server state
- account rate-limit snapshots
- persisted goal state
- the streamctl SQLite exchange store
- materialized thread and turn history
- rollout transcript files
- the wakectl SQLite queue

Those surfaces can be out of sync. Code and docs should not imply stronger
consistency than Codex actually provides.

`codex-wakectl` is the most stateful package because it coordinates queued jobs,
condition cursors, leases, and delivery policy. Treat changes there as
coordination changes, not simple CLI plumbing.

`codex-streamctl` owns only append-only stream entries and cumulative reader
acknowledgements. Keep publication, notification, wake, and acknowledgement as
separate operations. An acknowledgement is a processed-through cursor, not a
delivery receipt.

`codex-threadctl` depends on materialized turn pagination and selected rollout
records. It owns synchronous app-server start, steer, resume, and interruption
operations used by wakectl, plus advisory item injection and empty-turn wake.
Keep message locators composite and preserve the distinction between accepted
requests, confirmed delivery, and persisted history.

`codex-readcov` reports transcript-recorded read actions, not verified file
access or an operating-system audit log. It must reject unresolved dynamic
command envelopes instead of silently under-counting. `codex-goalctl replace`
is clear-then-set.

`codex-limitctl` owns read-only account capacity and usage signals. Keep current
account reads distinct from account-unscoped rollout history, normalize windows
by limit id and duration, and never pass through credit data or consumable
resets.

## Working Rules

- Keep package READMEs short and user-facing.
- Keep package docs neutral. They should describe package mechanics,
  tradeoffs, and failure modes; they should not read like instructions to a
  particular agent.
- Keep skill bodies agent-facing and operational. Skills should teach when to
  use a command, which primitive to choose, and what convention to follow.
- Keep skill references additive. Do not copy the skill quickstart into
  references; use references for low-level mechanics, edge cases, and
  troubleshooting.
- Split docs by purpose when a catch-all page starts mixing semantics,
  practices, and troubleshooting.
- Keep generated skill references in sync with
  `python3 scripts/sync-skill-references.py`.
- Preserve explicit binary names such as `codex-goalctl`; `ferrumctl` is the
  repository and suite name, not a command.
- When depending on Codex app-server methods, transcript schema, or parser
  output, keep the dependency narrow and name it in docs or tests.
- Test stateful workflows through persisted command transitions, not only the
  helper functions that calculate each step.
- Keep delegated review focused: use at most two reviewers at `xhigh` effort,
  and do not use `max`.
- Use `scripts/update-local.py` after changing locally installed commands or
  plugins. `codex plugin add` updates files on disk, but does not invalidate a
  separate persistent app-server's plugin cache.
