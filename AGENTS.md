# AGENTS

`ferrumctl` is a small suite of host tools for Codex power users. The packages
should feel like ordinary Unix commands: narrow purpose, predictable output,
clear exit status, and easy composition with shell tools.

## Design Posture

Prefer boring primitives over orchestration frameworks. A command should expose
one useful operation on one state surface; workflows belong in docs, skills, or
the caller's script.

Keep the CLI layer neutral. Skills may recommend an opinionated Codex workflow,
but the binaries should remain useful when installed and used separately.

Avoid convenience abstractions until the repeated use case is obvious. In
particular, do not introduce a suite wrapper, shared daemon, cross-package
runtime dependency, or common library just to make the repo look unified.

## System Boundaries

The tools touch three different Codex surfaces:

- live app-server state
- persisted goal state
- rollout transcript files

Those surfaces can be out of sync. Code and docs should not imply stronger
consistency than Codex actually provides.

`codex-wakectl` is the most fragile package because it coordinates live turns,
queued jobs, thread status, and app-server transport. Treat changes there as
coordination changes, not simple CLI plumbing.

`codex-readcov` is transcript coverage, not an operating-system audit log.
`codex-goalctl replace` is clear-then-set, not an atomic app-server primitive.

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
