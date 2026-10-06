---
name: codex-goalctl
description: "Use when another Codex thread's persisted goal must be read, or when a directly controlled thread's goal must be assigned, updated, or cleared. Use built-in goal tools for this session. Goalctl requires a thread id; resolve a canonical task name through the threadctl skill when available. It does not message or wake the target, and current Codex reserves goal changes on parent-owned v2 children for their native workflow."
---

# Codex Goalctl

## Purpose

Use `codex-goalctl` to manage another Codex thread's persisted goal from the
host. Each command starts a short-lived stdio app-server; no shared app-server
is required.

Goal state and thread execution are separate. A successful write does not start
a turn or guarantee that the target observes the change.

## Choose A Primitive

- `get` reads the current goal.
- `update` edits an existing goal and preserves its counters.
- `replace` clears the current goal and creates a fresh assignment.
- `clear` removes the goal.

Valid statuses are `active`, `paused`, `blocked`, `budgetLimited`,
`usageLimited`, and `complete`.

Use `replace` for a new assignment and `update` when elapsed time and token
usage should continue:

```sh
codex-goalctl replace THREAD_ID "objective text"
codex-goalctl get THREAD_ID
codex-goalctl update THREAD_ID "reworded objective"
codex-goalctl update THREAD_ID --status active
codex-goalctl update THREAD_ID --token-budget 50000
codex-goalctl update THREAD_ID --clear-token-budget
codex-goalctl clear THREAD_ID
```

For v1 Codex subagents, the spawn result's `agent_id` is the thread id. Some
native subagent tools instead return a canonical task name such as
`/root/reviewer`; it is not a goal identifier. If the threadctl skill is
available, resolve it first for goal reads:

```sh
WORKER=$(codex-threadctl resolve /root/reviewer)
codex-goalctl get "$WORKER"
```

`CODEX_THREAD_ID` supplies the tree scope. Otherwise pass `--tree THREAD_ID` to
`resolve`. Current Codex rejects external `replace`, `update`, and `clear` for a
parent-owned v2 child. Give that child its assignment through the native parent
workflow. When external goal control is required and the threadctl skill is
available, create an independent root from the outset:

```sh
WORKER=$(codex-threadctl create --cwd "$PWD")
codex-goalctl replace "$WORKER" "objective text"
```

## Start The Work

Prefer native control when the target's live subagent handle is available.
For an independent root, if the threadctl skill is available, continue from the
assigned goal without adding user input:

```sh
codex-threadctl wake "$WORKER" --resume
```

`--resume` permits loading on the selected server; reapply any worker-specific
configuration file when cold loading requires it. Keep the objective in goal
state. Setting `paused` changes persisted status; it does not interrupt an active
turn. A missing token budget means unbounded work, not a default allowance.

Use `--json` when another program will parse output.

## References

- Read `references/goal-lifecycle.md` for reset semantics, status transitions,
  token budgets, counters, and output behavior.
- Read `references/app-server-boundaries.md` for transport, thread-id
  reachability, and the boundary between goal writes and thread execution.
- Read `references/coordination-principles.md` when composing goals with native
  controls, messages, or scheduled wakes.
- Read `references/worker-workflows.md` for self-managed, coordinator-worker,
  supervision, and reviewer combinations.
