---
name: codex-wakectl
description: Use when acting as a Codex orchestrator or coding agent that needs to wake app-server-backed Codex CLI threads with the host codex-wakectl command. Covers immediate wakes, scheduled time/goal/command wakes, running the wake queue, installing the user systemd timer, and avoiding accidental overlapping turns. Do not use for ordinary terminal input injection or sessions that are not connected to a Codex app-server.
---

# Codex Wakectl

## Purpose

Use this skill when the current Codex session needs to send or schedule normal
input turns for Codex CLI threads connected to `codex app-server`.

`codex-wakectl` is a local wake scheduler. It does not manage goals, parse
transcripts, spawn agents, or inject keystrokes into terminals. It sends
app-server `turn/start` requests when asked directly or when a persisted wake
condition becomes true.

Assume `codex-wakectl` is installed on the host.

## App-Server Requirement

Use a shared app-server and connect target Codex sessions to it:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Only loaded threads can be woken. Check the endpoint and loaded threads before
debugging a missed wake:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
```

Pass `--endpoint unix://PATH` when the target session uses a non-default socket.

## Immediate Wakes

Send one normal input turn:

```sh
codex-wakectl send THREAD_ID "A goal was assigned. Call get_goal and proceed."
```

By default, `send` refuses to start a turn while the target thread is active.
Use `--allow-active` only when an overlapping turn is intentional; overlapping
turns can interleave and do not behave like clean independent conversations.

## Scheduled Wakes

Persist wake jobs:

```sh
codex-wakectl add time --after 30m --to THREAD_ID "Wake up and check status."
codex-wakectl add time --at 2026-06-04T18:30:00Z --to THREAD_ID "Run the check."
```

Queued wakes also refuse to start while the target thread is active. If one
specific queued wake should overlap, mark that job when it is created:

```sh
codex-wakectl add time --after 30m --to THREAD_ID --allow-active "Run even if active."
```

Wake an orchestrator when a worker goal stops:

```sh
codex-wakectl add goal WORKER_THREAD_ID \
  --status complete,budgetLimited,usageLimited,blocked \
  --to ORCH_THREAD_ID \
  "Worker goal stopped. Inspect it and decide the next step."
```

Wake on goal usage milestones:

```sh
codex-wakectl add goal WORKER_THREAD_ID --tokens-used-every 3000000 --to ORCH_THREAD_ID "Worker crossed another 3000000-token boundary."
codex-wakectl add goal WORKER_THREAD_ID --time-used-every 30m --to ORCH_THREAD_ID "Worker crossed another 30m boundary."
```

Use command predicates for external conditions. Exit status `0` means ready:

```sh
codex-wakectl add cmd --to THREAD_ID "The predicate is true." -- sh -c 'test -f done.txt'
```

Command predicates run from the directory where the job was created. Make them
self-contained; a systemd timer may not have the same shell environment.
The job timeout also bounds the predicate command so a stuck predicate cannot
hold a runner forever.

## Queue Processing

Process pending jobs once:

```sh
codex-wakectl run
```

Install the canonical recurring runner:

```sh
codex-wakectl systemd install --interval 30s
```

This writes user units under `~/.config/systemd/user/` and enables
`codex-wakectl.timer`. Remove them with:

```sh
codex-wakectl systemd uninstall
```

Use `run` in scripts and tests. Use the systemd timer for normal long-term
scheduling. Do not invent a separate long-running daemon unless the user asks
for a different supervision model.

Wake jobs store their endpoint, timeout, and overlap policy when created, so a
later systemd `run` can process them without recreating the original shell
context.

## Orchestrator Pattern

1. Identify the worker and orchestrator thread ids. For Codex subagents, the
   `agent_id` returned by spawn is the thread id.
2. Assign durable work with `codex-goalctl` when goal management is needed.
3. Wake the worker immediately with `codex-wakectl send`.
4. Schedule wakes back to the orchestrator for goal completion, budget limits,
   token milestones, time milestones, or command predicates.
5. When woken, inspect goal state and optional read coverage, then decide the
   next worker action.

Example:

```sh
codex-goalctl replace "$WORKER" "Investigate the parser issue and mark the goal complete."
codex-wakectl send "$WORKER" "A goal was assigned. Call get_goal and proceed."
codex-wakectl add goal "$WORKER" --status complete,blocked,budgetLimited,usageLimited --to "$ORCH" "Worker goal stopped. Inspect it."
```

## Rules

- Prefer `send` for immediate wakes and `add` plus `run`/systemd for scheduled
  wakes.
- Keep wake messages idempotent; a failed or retried runner may send later than
  expected.
- Use `--json` when another program will parse output.
- Use `list`, `list --all`, and `cancel WAKE_ID` to inspect or remove jobs.
- Do not assume `codex-wakectl` can wake sessions that are not loaded on the
  selected app-server.
- Do not use `--allow-active` casually. The default active-thread refusal is a
  guard against accidental overlapping turns.

## Quick Reference

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
codex-wakectl send THREAD_ID MESSAGE
codex-wakectl add time --after 10m --to THREAD_ID MESSAGE
codex-wakectl add time --after 10m --to THREAD_ID --allow-active MESSAGE
codex-wakectl add goal THREAD_ID --status complete --to ORCH_THREAD_ID MESSAGE
codex-wakectl add cmd --to THREAD_ID MESSAGE -- COMMAND...
codex-wakectl run
codex-wakectl systemd install --interval 30s
codex-wakectl list --all
codex-wakectl cancel WAKE_ID
```
