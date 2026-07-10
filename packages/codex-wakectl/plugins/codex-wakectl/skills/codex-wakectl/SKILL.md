---
name: codex-wakectl
description: "Use when you need the host codex-wakectl command to send or schedule a normal input turn for a Codex CLI thread through app-server, wait for a Codex condition, or manage wake jobs. Covers immediate thread-id delivery, time, goal, turn-completion and command conditions, self-wakes, supervisor wakes, peer handoffs, queue runners, and repeating milestones. Do not use for thread inspection or interruption, goal editing, transcript coverage, terminal injection, agent spawning, targets not loaded on the selected app-server, or jobs you do not own."
---

# Codex Wakectl

## Purpose

Use this skill when this session needs to deliver input through a Codex thread
id, block on a Codex condition, or arrange a later input turn.

Assume `codex-wakectl` is installed on the host. It sends normal user input and
persists conditional wake jobs for a runner. It does not inspect thread history,
interrupt work, edit goals, parse transcripts, inject terminal input, or spawn
agents.

Wakes continue the target's existing context and remain in its transcript.
Immediate input can be the instruction. Queued input may arrive late or more
than once, so it often works best as a short event marker.

## Choosing The Channel

Use native subagent input when this session owns the live handle and needs to
send an immediate message. Use native wait or poll when this turn should remain
active and blocking is acceptable.

Use `codex-wakectl send` when the useful handle is a thread id or host-level
delivery is intentional. Use `wait` for a blocking condition with an exit code.
Use `add` when this turn should end and a runner should resume attention later.

When target state is unclear and the `codex-threadctl` skill is available,
inspect before choosing the delivery policy.

## App Server

The target must be loaded on the selected endpoint:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Use `--endpoint unix://PATH` for a non-default server. For this thread's
identity, use:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

Identity does not prove wakeability. If `codex-threadctl` is also available,
`codex-threadctl loaded` shows the selected server's loaded thread ids.

## Patterns

Send input now:

```sh
codex-wakectl send TARGET "Check status and continue if useful."
```

Schedule a self-check:

```sh
codex-wakectl add time --after 30m --to SELF "Time check."
```

Wake a coordinator when a goal reaches a terminal status:

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

Wake after a later turn ends, including one that starts and finishes between
runner passes:

```sh
codex-wakectl add stop WORKER --to COORDINATOR "Worker turn ended."
```

Wake on a host-visible predicate:

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

Inspect the shared queue and cancel only an owned job:

```sh
codex-wakectl list
codex-wakectl cancel JOB_ID
```

## Conventions

- Prefer native subagent input when the live handle is available. Use wakectl
  for thread-id delivery, self or peer coordination, and future conditions.
- A wake is input to its target, not a result returned to its sender. Retrieve
  native results through the native handle; otherwise use deliberate thread
  inspection or a shared artifact when those surfaces are available.
- Send to idle targets for ordinary follow-up. Use `send --allow-active` only
  for input that remains valid while current work continues.
- Treat `idle` as no running turn, not as permission for unrelated work. An
  idle worker can retain an active goal.
- When a goal was assigned externally, a short message asking the worker to
  call `get_goal` can start or resume it.
- Goal completion and turn completion are separate. If the final response
  matters, observe the turn boundary after a terminal goal wake.
- For a blocking checkpoint, prevent automatic continuation first. Pause the
  goal when `codex-goalctl` is available, and stop active work through a native
  handle or `codex-threadctl` when that skill is available. Arm the stop watch
  before sending the question.
- Create a stop watch before the turn it should observe. Prior terminal turns
  are not replayed.
- Treat repeating goal watches as belonging to one assignment. Cancel an old
  watch when it should not supervise a replacement goal.
- Keep queued messages short unless delayed, duplicate delivery is deliberately
  the instruction. Do not store evolving approvals, full plans, or project
  state in wake text.
- Treat queued delivery as at-least-once. A wake can arrive late, duplicate, or
  become redundant after manual handling.
- Keep command predicates cheap and repeatable. They retain argv and cwd but
  run in the runner's environment, which may differ under systemd.
- Verify job id, target, condition, and message before canceling. The default
  queue is shared and proximity does not imply ownership.

## References

- Read `references/runtime-semantics.md` when condition matching, durable turn
  cursors, repeating jobs, delivery guarantees, or SQLite behavior matters.
- Read `references/coordination-practices.md` when choosing native input,
  blocking wait, queued wakes, active delivery, checkpoints, or result
  retrieval.
- Read `references/troubleshooting.md` when delivery fails, a job remains
  pending, or duplicate wakes appear.
- Read `references/coordination-principles.md` when composing wakes with native
  controls, goals, thread inspection, coverage, or partial skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  self-management, worker review, peer handoffs, or external managers.
- Read `references/operational-caveats.md` when retries, shared state, stale
  jobs, or cross-surface consistency matters.
