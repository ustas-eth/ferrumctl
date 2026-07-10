---
name: codex-wakectl
description: "Use when you need the host codex-wakectl command to wait for a Codex or host condition, schedule a normal input turn for later delivery through app-server, or manage durable wake jobs. Covers time, goal, turn-completion and command conditions, self-wakes, supervisor wakes, peer handoffs, queue runners, and repeating milestones. Do not use for immediate input, thread inspection or interruption, goal editing, read coverage, terminal injection, agent spawning, or jobs you do not own."
---

# Codex Wakectl

## Purpose

Use this skill when this session must block on a condition or arrange input that
survives the current turn.

Assume `codex-wakectl` is installed. It evaluates time, goal, turn-completion,
and command predicates and stores conditional input jobs for a runner. It does
not provide immediate thread control, inspect history, edit goals, or spawn
agents.

Queued messages continue the target's existing context and remain in its
transcript. Delivery can be delayed or duplicated, so a short event marker is
usually better than a copied plan.

## Choosing The Primitive

Use native wait or poll when this turn should stay active and blocking is
acceptable. Use `wait` when a script or thread-id-only controller needs a
blocking condition and an exit status. Use `add` when this turn should end and
a runner should deliver input after a later condition.

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
codex-wakectl add time --after 30m --to "$SELF" "Time check."
```

Wake a coordinator when one goal assignment reaches a terminal status:

```sh
codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to COORDINATOR \
  "Worker goal reached a terminal status."
```

Wake on later goal-usage milestones:

```sh
codex-wakectl add goal WORKER --tokens-used-every 2000000 \
  --max-fires 4 --to COORDINATOR \
  "Worker token milestone."
```

Wake after a later turn ends:

```sh
codex-wakectl add stop WORKER --to COORDINATOR "Worker turn ended."
```

Wake on a host predicate:

```sh
codex-wakectl add cmd --to PEER "Input is ready." -- sh -c 'test -f done.txt'
```

Block without sending input:

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
- Use `--allow-active` only when the message remains valid in the current
  regular turn. The runner obtains its current turn id and uses native
  expected-turn steering.
- Treat queued delivery as at-least-once. Jobs with an unconfirmed submission
  become `uncertain` instead of being retried automatically.
- A wake is input to its target, not a result returned to its sender. Retrieve
  results through a native handle, thread inspection, or a shared artifact when
  the corresponding surface is available.
- Create a stop watch before the turn it should observe. Missing or rewritten
  cursor history fails the job rather than replaying an older completion.
- A goal watch binds to the assignment visible when it is created, or to the
  first assignment observed if none exists yet. A replacement goal supersedes
  the old watch.
- Goal completion and turn completion are separate. Observe the later turn
  boundary when the final response matters.
- Keep queued messages short unless delayed duplicate delivery is deliberately
  the instruction. Do not store evolving approvals or project state in wake
  text.
- Keep command predicates cheap and repeatable. They retain argv and cwd but
  run in the runner's environment.
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
  blocking wait, scheduled wakes, active steering, checkpoints, or result
  retrieval.
- Read `references/troubleshooting.md` when delivery fails, a job remains
  pending, or a job becomes failed or uncertain.
- Read `references/coordination-principles.md` when composing wakes with native
  controls, goals, thread inspection, coverage, or partial skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  self-management, worker review, peer handoffs, or external managers.
- Read `references/operational-caveats.md` when retries, shared state, stale
  jobs, or cross-surface consistency matters.
