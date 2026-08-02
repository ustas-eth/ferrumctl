# AGENTS

`ferrumctl` is a small suite of host tools for Codex power users. Its packages
should feel like ordinary Unix commands: narrow in purpose, predictable in
output, explicit about failure, and easy to compose.

## Engineering Posture

Prefer simple primitives over orchestration frameworks. A command should expose
one useful operation on one state surface; workflows belong in the caller,
documentation, or an optional skill.

Let interfaces carry semantics. Prefer command structure, typed values, output
fields, exit status, and tests over prose that tells an agent how to reason.
Examples should clarify syntax or composition without making one workflow look
mandatory.

Use judgment where the codebase and surrounding context provide enough
information. Add a durable rule only for a non-obvious invariant, product
decision, or recurring failure that cannot be designed away. When misuse
recurs, first ask whether the command boundary, naming, or output can make the
correct choice clearer.

Keep each CLI useful on its own. Do not add a suite wrapper, shared daemon, or
common library merely for uniformity. A cross-package dependency must represent
a real behavioral dependency; wakectl uses threadctl's client because deferred
and immediate delivery must share the same turn-scoped app-server operations.

## Context Discipline

Treat this file as durable workspace context, not a development manual. Keep
project purpose, architectural boundaries, lasting preferences, and expensive
gotchas here. Put command syntax in help, package mechanics in docs, and
task-specific decisions in the relevant work.

Do not repeat guidance across `AGENTS.md`, skills, references, and READMEs just
to make it more forceful. Give each fact one natural home and reference it when
needed. Preserve important constraints, but avoid blanket instructions that
replace sound engineering judgment.

## System Boundaries

The tools observe or mutate independent state surfaces:

- live app-server state
- materialized thread and turn history
- persisted goal state
- rollout transcript files
- account rate-limit snapshots
- the streamctl SQLite exchange store
- the wakectl SQLite queue

These surfaces can differ in freshness and can disagree without either being
corrupt. Code, output, and documentation must identify the source being
reported and must not imply stronger consistency than Codex provides.

A read-only orientation command may combine observations when that removes
guesswork, provided each source retains its meaning and freshness. A mutating
command should remain bound to one state surface.

## Package Contracts

- `codex-goalctl` manages persisted goal state. Goal writes do not wake a
  thread, and `replace` is intentionally a fresh clear-then-set assignment.
- `codex-threadctl` combines live app-server operations with selected persisted
  history. Preserve composite message locators and distinguish request
  acceptance, confirmed delivery, and materialized history. Agent paths are
  tree-scoped aliases; they do not transfer v2 lifecycle ownership from the
  native parent.
- `codex-wakectl` coordinates durable jobs, condition cursors, leases, and
  delivery policy. It is the most stateful package; treat changes to it as
  coordination changes rather than ordinary CLI plumbing.
- `codex-streamctl` owns append-only entries and cumulative processed-through
  acknowledgements. Publication, notification, wake, and acknowledgement are
  separate operations; an acknowledgement is not a delivery receipt.
- `codex-readcov` reports transcript-recorded read actions, not verified file
  access or an operating-system audit log. Reject evidence that cannot be
  resolved reliably rather than silently under-counting it.
- `codex-limitctl` exposes read-only capacity and usage signals. Keep current
  account reads distinct from account-unscoped rollout history, and do not
  expose credit data or consumable resets.

## Documentation Roles

- Package READMEs give humans a quick understanding of value and installation.
- Command help is the primary syntax reference.
- Package docs describe mechanics, tradeoffs, and failure modes in neutral
  language.
- Skill descriptions route an agent to the right capability and state only the
  exclusions needed to prevent likely misuse.
- Skill bodies explain primitive selection and operational invariants from the
  acting agent's point of view.
- Skill references add low-level semantics, edge cases, and troubleshooting;
  they do not repeat the quickstart.

Split a document when it starts mixing distinct purposes. Keep generated skill
references synchronized with `python3 scripts/sync-skill-references.py`.
Preserve explicit binary names such as `codex-goalctl`; `ferrumctl` is the
repository and suite name, not a command.

## Development

Keep dependencies on Codex app-server methods, transcript schemas, and parser
output narrow and visible in documentation or tests. Test stateful behavior
through persisted command transitions, not only helper functions.

Follow `CONTRIBUTING.md` for verification and commit conventions. Keep delegated
review focused: use at most two reviewers at `xhigh` effort, never `max`.

Use `scripts/update-local.py` after changing locally installed commands or
plugins. `codex plugin add` updates files on disk but does not invalidate a
separate persistent app-server's plugin cache.
