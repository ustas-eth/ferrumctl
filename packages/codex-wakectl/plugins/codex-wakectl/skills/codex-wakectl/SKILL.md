---
name: codex-wakectl
description: "Use when you need the host codex-wakectl command to inspect recent activity, interrupt an active turn, or send or schedule a normal input turn for a Codex CLI thread through app-server. Covers thread visibility, immediate sends, time, goal, turn-completion, and command conditions, self-wakes, supervisor wakes, checkpoints, peer handoffs, queue runners, and repeating milestones. Do not use for terminal input injection, goal editing, transcript coverage, agent spawning, sending to a target not loaded on the selected app-server, or canceling jobs you do not own."
---

# Codex Wakectl

## Purpose

Use this skill when a Codex thread needs app-server visibility, live turn
control, or a later input turn.

Assume `codex-wakectl` is installed on the host. It can inspect recent activity,
interrupt an active turn, send normal input, and persist conditional wakes. It
is not a terminal input injector, goal editor, raw transcript parser, or agent
spawner.

Wakes are normal user input. The target continues its existing thread, and the
message remains in its transcript. Immediate input may carry an instruction;
queued input may arrive late or more than once and usually works best as a small
event marker.

## Model

Thread status, goal status, and turn history answer different questions:

- thread status says whether a turn is active now
- goal status describes durable assignment state
- turn history shows recent responses and structured activity

A queued wake has a condition, a target thread, sometimes a different watched
thread, and a runner that evaluates pending jobs. The default queue is shared by
all workflows using the same host user and state path.

## Choosing The Channel

Inspect another thread when its current state is not already clear:

```sh
codex-wakectl inspect THREAD_ID
```

Use native subagent input for an immediate message when this session has the
live subagent handle. Use native wait or poll when this turn should stay active
and blocking is acceptable.

Use `codex-wakectl` when the useful handle is a thread id, when a session needs
self/peer/external coordination, or when a condition should resume attention
later.

## App Server

The selected app-server endpoint defines live control:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Check thread reachability and activity:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
codex-wakectl inspect THREAD_ID
```

Sending and interrupting require the target to be loaded on that endpoint.
Inspection can also read persisted turns from a thread that is not loaded.

Use `--endpoint unix://PATH` when the shared server is not the default. For the
current thread, use `CODEX_THREAD_ID`:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl status "$SELF"
```

The environment variable proves identity, not wakeability. App-server `idle`
means no turn is running; it does not mean the thread lacks an active goal or is
available for unrelated work.

## Patterns

Use real Codex thread ids for placeholders.

Inspect before intervening in unfamiliar work:

```sh
codex-wakectl inspect WORKER
```

Send immediate input through wakectl when it is the chosen channel:

```sh
codex-wakectl send TARGET "Check status and continue if useful."
```

Interrupt the active turn. Inspect first unless interruption was already the
explicit decision:

```sh
codex-wakectl interrupt TARGET
```

Schedule a self-check:

```sh
codex-wakectl add time --after 30m --to SELF "Time check. Review progress."
```

Wake a coordinator when a goal reaches a terminal status:

```sh
codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to COORDINATOR \
  "Worker goal reached a terminal status. Inspect it."
```

Wake on a goal milestone:

```sh
codex-wakectl add goal WORKER --tokens-used-every 2000000 \
  --max-fires 4 --to COORDINATOR \
  "Worker token milestone. Reassess."
```

Wake after a later turn ends, even if it starts and finishes between runner
passes:

```sh
codex-wakectl add stop WORKER --to COORDINATOR \
  "Worker turn ended. Inspect it."
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

Inspect the shared queue and cancel only a job owned by this workflow:

```sh
codex-wakectl list
codex-wakectl cancel JOB_ID
```

## Conventions

- Inspect before steering, interrupting, or reassigning a thread whose state is
  unclear.
- Prefer native subagent input when the live handle is available. Use wakectl
  for thread-id control, self/peer coordination, and future conditions.
- A wake is input to its target, not a result returned to its sender. Retrieve a
  native subagent result through the native handle; otherwise inspect the
  thread or use a shared result artifact.
- Goal completion and turn completion are separate. After a terminal goal wake,
  inspect the worker or wait for its active turn to end before relying on the
  final response.
- For a blocking checkpoint, prevent automatic continuation first. When the
  `codex-goalctl` skill is available for a goal-backed worker, pause its goal;
  interrupt it if a turn is active, then arm a stop watch and send the question.
- Send to idle targets for ordinary follow-up. Use `send --allow-active` only
  for a reminder or correction that can be applied while the current turn
  continues.
- An idle worker with an active goal has durable work but no running turn. A
  short message telling it to call `get_goal` often starts or resumes the work.
- Create a stop watch before the turn it should observe. The watch records the
  current newest turn as its cursor; prior completed turns are not replayed.
- Treat a repeating goal watch as part of one assignment. Cancel it when it
  should not continue supervising a replacement goal; otherwise its milestone
  cursor rebases to the new goal without firing.
- Keep queued messages short unless delayed, repeated delivery is deliberately
  the instruction. Do not store evolving approval history, full plans, or
  project state in wake text.
- Treat queued delivery as at-least-once. A wake can arrive late, duplicate, or
  become redundant after manual handling.
- Keep command predicates cheap and repeatable. They retain argv and cwd but
  execute in the runner's environment, which may differ under systemd.
- Before canceling, verify the job id, target, condition, and message. The queue
  is shared and proximity does not imply ownership.

## References

- Read `references/runtime-semantics.md` when inspection, interruption, durable
  turn cursors, repeating conditions, delivery guarantees, or SQLite state
  behavior matters.
- Read `references/coordination-practices.md` when choosing native input,
  native wait/poll, synchronous wait, queued wakes, steering, checkpoints, or
  result retrieval.
- Read `references/troubleshooting.md` when inspection or delivery fails, a job
  stays pending, or duplicate wakes appear.
- Read `references/coordination-principles.md` when composing live control with
  goals, native handles, transcript coverage, or partial skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  self-management, main/worker review, active supervision, reviewer chains,
  peer handoffs, or external managers.
- Read `references/operational-caveats.md` when retries, shared state, stale
  jobs, result boundaries, or cross-surface consistency matters.
