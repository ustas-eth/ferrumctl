---
name: codex-wakectl
description: "Use when input must be delivered to a Codex thread after a later time, goal, turn-completion, or host condition, or when durable wake jobs and runners must be managed. Also covers synchronous goal or turn waits for scripts and thread-id-only controllers. Do not use to monitor a terminal process this turn already owns; use native process polling. Do not use for immediate input, thread inspection or interruption, goal editing, read coverage, terminal injection, agent spawning, or jobs you do not own."
---

# Codex Wakectl

## Purpose

Use this skill to arrange input that survives the current turn. `add` persists a
condition and message for later runner delivery.

`wait` is a secondary synchronous interface for scripts and thread-id-only
controllers. It blocks only its invoking process, sends no input, creates no
job, and does not start or resume a Codex turn when it finishes.

Assume `codex-wakectl` is installed. It evaluates time, goal, turn-completion,
and command predicates and stores conditional input jobs for a runner. It does
not provide immediate thread control, inspect history, edit goals, or spawn
agents.

Queued messages continue the target's existing context and remain in its
transcript. Delivery can be delayed or duplicated, so a short event marker is
usually better than a copied plan.

## Choosing The Primitive

Choose by what should happen to the caller. Use native wait or poll when this
turn owns the live subagent or terminal handle and should stay active. Use
`wait goal` or `wait stop` when a script or thread-id-only controller needs an
exit status from Codex state. Use `add` when this turn should end and a runner
should deliver input after a later condition.

Use native subagent input for immediate messages when the live handle is
available. If only a thread id is available and the `codex-threadctl` skill is
also available, use threadctl for immediate start or steering.

## Setup

The wake target must be loaded on the selected app-server when delivery occurs:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Use `--endpoint unix://PATH` for a non-default server. For this thread's
identity:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

## Patterns

Schedule a self-check:

```sh
codex-wakectl add time --after 30m --to "$SELF" \
  "Self-scheduled reminder: Review progress."
```

Wake a coordinator when one goal assignment reaches a terminal status:

```sh
codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to COORDINATOR \
  "Automated event: Worker goal reached a terminal status."
```

Wake on later goal-usage milestones:

```sh
codex-wakectl add goal WORKER --tokens-used-every 2000000 \
  --max-fires 4 --to COORDINATOR \
  "Automated event: Worker token milestone."
```

Wake after a later turn ends:

```sh
codex-wakectl add stop WORKER --to COORDINATOR \
  "Automated event: Worker turn ended."
```

Bind a wake to one turn when its id is known or watch creation may race its
completion:

```sh
codex-wakectl add stop WORKER --turn TURN_ID --to COORDINATOR \
  "Automated event: Worker turn ended."
```

Wake on a host predicate:

```sh
codex-wakectl add cmd --to PEER \
  "Automated event: Input is ready." -- sh -c 'test -f done.txt'
```

For a long self-managed wait, target both the condition and its recovery check
at the session that owns the wait:

```sh
codex-wakectl add cmd --to "$SELF" \
  "Automated event: Input is ready." -- test -f done.txt
codex-wakectl add time --after 2h --to "$SELF" \
  "Self-scheduled reminder: Check wake-watch health."
```

Synchronously gate a script or thread-id-only controller:

```sh
codex-wakectl wait goal WORKER --status complete,blocked --max-wait 30m
codex-wakectl wait stop WORKER --max-wait 30m
```

Process the queue once, or install the recurring runner:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
```

Inspect the shared queue and cancel only an owned pending job:

```sh
codex-wakectl list
codex-wakectl cancel JOB_ID
```

## Conventions

- By default, a ready wake waits for the target to appear idle and starts a new
  turn. The idle check is not atomic; recorded delivery mode is authoritative.
- Label queued input by meaning when its source could be ambiguous:
  `Self-scheduled reminder:` for this thread's earlier note, `Automated event:`
  for a condition notice, or `From coordinator:` for authored direction. Name
  wakectl only when transport matters. A source label does not override
  existing instructions.
- Use `--allow-active` only when the message remains valid in the current
  regular turn. The runner obtains its current turn id and uses native
  expected-turn steering.
- Treat queued delivery as at-least-once. Jobs with an unconfirmed submission
  become `uncertain` instead of being retried automatically.
- A wake is input to its target, not a result returned to its sender. Retrieve
  results through a native handle, thread inspection, or a shared artifact when
  the corresponding surface is available.
- An unqualified stop watch records a boundary. Create it before the turn it
  should observe.
- Use `--turn TURN_ID` to observe that exact turn even if it has already ended.
  Use `--turn latest` only when the newest existing turn is deliberately the
  target. Missing or rewritten turn history fails the job rather than replaying
  an older completion.
- A goal watch binds to the assignment visible when it is created, or to the
  first assignment observed if none exists yet. A replacement goal supersedes
  the old watch.
- Goal completion and turn completion are separate. Observe the later turn
  boundary when the final response matters.
- Do not wrap a running terminal owned by this turn with `wait cmd`; poll the
  original terminal directly. `wait cmd` only adds another polling process and
  does not schedule later input.
- Keep queued messages short unless delayed duplicate delivery is deliberately
  the instruction. Do not store evolving approvals or project state in wake
  text.
- Treat an `add cmd` command as a level-triggered probe, not as the work being
  scheduled. It may run many times with discarded output. Keep it cheap and
  side-effect free, and return `0` while the wake remains actionable.
- Use a separate watcher when detection needs state, backoff, diagnostics, or
  expensive work. Give that host process an explicit lifecycle and cleanup
  owner. Prefer to persist readiness, then make the wakectl predicate a simple
  test of that state.
- Before leaving a long command watch unattended, exercise both predicate
  outcomes when practical and inspect the job after its configured runner has
  evaluated it once. Do not run the shared queue solely to test one job.
- When a missed condition would otherwise require user intervention, add a time
  wake for the session that owns and can repair the wait. Record both job ids
  and cancel the pending counterpart after either path is handled.
- A not-loaded target remains pending. Resume it deliberately through its
  normal owner or through threadctl when that skill is available.
- Do not use v2 subagents as wake targets; Codex requires their native parent
  handle for direct input.
- The default queue is shared. Verify job id, target, condition, and message
  before canceling.

## References

- Read `references/runtime-semantics.md` when condition matching, goal identity,
  stop cursors, delivery outcomes, leases, or SQLite behavior matters.
- Read `references/coordination-practices.md` when choosing native wait,
  blocking wait, scheduled wakes, long host watchers, recovery deadlines,
  active steering, checkpoints, or result retrieval.
- Read `references/troubleshooting.md` when delivery fails, a job remains
  pending, or a job becomes failed or uncertain.
- Read `references/coordination-principles.md` when composing wakes with native
  controls, goals, thread inspection, coverage, or partial skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  self-management, worker review, peer handoffs, or external managers.
- Read `references/operational-caveats.md` when retries, shared state, stale
  jobs, or cross-surface consistency matters.
