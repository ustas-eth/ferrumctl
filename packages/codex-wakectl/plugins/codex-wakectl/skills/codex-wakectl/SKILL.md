---
name: codex-wakectl
description: Use when you need the host codex-wakectl command to send or schedule a normal input turn for the current Codex thread or another loaded app-server-backed Codex CLI thread. Covers immediate sends, time/goal/stop/command conditions, self-wakes, supervisor wakes, peer handoffs, queue runners, repeating milestones, and avoiding duplicate or overlapping turns. Do not use for terminal input injection, goal editing, transcript coverage, agent spawning, or sessions not connected to the same Codex app-server.
---

# Codex Wakectl

## Purpose

Use this skill when a Codex thread needs to wake itself or another Codex thread
through `codex app-server`.

Assume `codex-wakectl` is installed on the host. It sends normal app-server
input turns. It is not a terminal input injector, goal manager, transcript
parser, or agent spawner.

## Model

A queued wake has:

- a **condition**: when the wake should fire
- a **target thread**: the thread that receives the message
- sometimes a **watched thread**: the thread whose goal or activity is observed
- a **runner**: `codex-wakectl run`, systemd, or another scheduler that checks
  queued jobs

The watched thread and target thread may be the same.

## App Server

```sh
codex app-server --listen unix://
codex --remote unix://
```

Only loaded threads on the selected app-server can be woken. Check that first:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
```

Use `--endpoint` when the shared app-server is not the default `unix://`:

```sh
codex-wakectl --endpoint unix://PATH status THREAD_ID
```

To target the current thread:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl status "$SELF"
```

`CODEX_THREAD_ID` identifies the current Codex thread. It does not prove the
thread is wakeable. If `status` fails or says `not-loaded`, do not queue
self-wakes until the correct `--endpoint` is known or the session is connected
to the shared app-server.

## Patterns

Use actual Codex thread ids for placeholders such as `SELF`, `TARGET`,
`WORKER`, `COORDINATOR`, and `PEER`.

Immediate wake to a loaded target:

```sh
codex-wakectl send TARGET "Check status and continue if useful."
```

Self wake for a later check:

```sh
codex-wakectl add time --after 30m --to SELF "Time check: review progress and decide next step."
```

Self wake near a goal budget limit:

```sh
codex-wakectl add goal SELF --tokens-left-lte 300000 --to SELF "Token budget is low. Summarize or stop."
```

Supervisor wake: watch one thread and wake another:

```sh
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited --to COORDINATOR "Worker goal stopped. Inspect it."
```

Stop wake when no goal is assigned:

```sh
codex-wakectl add stop WORKER --to COORDINATOR "Worker stopped. Inspect it."
```

Peer handoff:

```sh
codex-wakectl add cmd --to PEER "Input is ready. Inspect done.txt and continue." -- sh -c 'test -f done.txt'
```

Milestone wake:

```sh
codex-wakectl add goal WATCHED --time-used-every 30m --to TARGET "Goal time milestone. Reassess."
codex-wakectl add goal WATCHED --tokens-used-every 3000000 --to TARGET "Token milestone. Reassess."
```

Repeating stop wake with a cap:

```sh
codex-wakectl add stop WORKER --repeat --max-fires 5 --to TARGET "Worker completed another turn. Inspect it."
```

Wait without sending a wake:

```sh
codex-wakectl wait goal WORKER --status complete,blocked --max-wait 30m
```

Use native subagent wait/poll when a native handle is available. Use
`codex-wakectl wait` when only a thread id and app-server condition are
available and synchronous blocking is acceptable. Use queued wakes when this
thread should end the current turn and be resumed later.

Process queued jobs once, or install the recurring runner:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
```

Inspect and cancel queued jobs:

```sh
codex-wakectl list
codex-wakectl cancel JOB_ID
```

## Conventions

- Prefer `send` for immediate messages and `add` plus `run`/systemd for queued
  wakes.
- Arm watches before the event they should observe can happen. In particular,
  create `stop` watches before starting the turn they should observe.
- Make every wake message idempotent and explicit: why it fired, what to check,
  and what action is expected.
- Treat queued delivery as at-least-once. A wake may arrive late, duplicate
  after a runner crash, or become redundant after manual handling.
- Avoid `--allow-active` unless overlapping turns are intentional.
- Keep command predicates cheap and safe to repeat.
- Cancel stale jobs when the supervision loop is over.
- In peer handoffs or delegated supervision, make ownership clear in the
  message: who should inspect, who should report upward, and who should cancel
  remaining jobs.

## References

- Read `references/runtime-semantics.md` when condition semantics, repeating
  wakes, delivery guarantees, active-turn refusal, or SQLite state behavior
  matter.
- Read `references/coordination-practices.md` when choosing between native
  wait/poll, `codex-wakectl wait`, and queued wakes, or when message hygiene,
  persisted job contents, current-thread identity, or script parsing matter.
- Read `references/troubleshooting.md` when a wake did not arrive, a job stays
  pending, or duplicate wakes appear.
- Read `references/orchestrator-worker-loop.md` when combining wakes with goals
  or read coverage.
