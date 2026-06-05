---
name: codex-wakectl
description: Use when acting as a Codex orchestrator or coding agent that needs to wake app-server-backed Codex CLI threads with the host codex-wakectl command. Covers immediate wakes, scheduled time/goal/stop/command wakes, running the wake queue, installing the user systemd timer, repeating milestones, and avoiding accidental overlapping turns. Do not use for ordinary terminal input injection or sessions that are not connected to a Codex app-server.
---

# Codex Wakectl

## Purpose

Use this skill when the current Codex session needs to send or schedule normal
input turns for Codex CLI threads connected to `codex app-server`.

Assume `codex-wakectl` is installed on the host. It is not a terminal input
injector, goal manager, transcript parser, or agent spawner.

## App-Server Requirement

Use a shared app-server and connect target sessions to it:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Check loaded threads before debugging a missed wake:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
```

## Workflow

Send one immediate wake:

```sh
codex-wakectl send THREAD_ID "A goal was assigned. Call get_goal and proceed."
```

Queue wakes:

```sh
codex-wakectl add time --after 30m --to THREAD_ID "Wake up and check status."
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited --to ORCH "Worker goal stopped. Inspect it."
codex-wakectl add stop WORKER --to ORCH "Worker stopped. Inspect it."
codex-wakectl add cmd --to THREAD_ID "Predicate is true." -- sh -c 'test -f done.txt'
```

Process queued jobs once:

```sh
codex-wakectl run
```

Install the canonical recurring runner:

```sh
codex-wakectl systemd install --interval 30s
```

## References

- Read `references/wake-scheduling.md` when stop edges, repeating wakes,
  command predicates, state, or overlapping-turn behavior matter.
- Read `references/orchestrator-worker-loop.md` when combining wakes with goals
  or read coverage.

## Rules

- Prefer `send` for immediate wakes and `add` plus `run`/systemd for scheduled
  wakes.
- Treat queued wakes as polling-backed notifications, not exact events.
- Keep wake messages idempotent; they may arrive late or after manual handling.
- Do not assume non-loaded or non-app-server sessions can be woken.
- Create `stop` watches before starting the turn they should observe.
- Avoid `--allow-active` unless overlapping turns are intentional.
- Cancel stale jobs when the supervision loop is over.
