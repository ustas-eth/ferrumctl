---
name: codex-goalctl
description: "Use when you need the host codex-goalctl command to inspect or change another Codex CLI thread/subagent's persisted goal: assign, update objective/status/token budget, clear, verify state, or spawn a subagent and set its goal. Do not use for your own task goal, ordinary worker-thread tasks, or built-in goal tools unless the user explicitly asks for codex-goalctl."
---

# Codex Goalctl

## Purpose

Use this skill when this Codex session is coordinating another Codex CLI thread
and needs to manage that thread's persisted goal state from the host.

Assume `codex-goalctl` is installed on the host. It reads and writes goal state
through a short-lived stdio app-server started for each command; it does not
send chat messages, spawn agents, or reliably wake a CLI-owned thread.

This is not a general planning tool. If you only need your current thread's
internal goal state, use the built-in goal tools when they are available.

## Model

- The target is a Codex thread id.
- For v1 Codex subagents, the spawn result's `agent_id` is the thread id.
- `get` reads the persisted goal.
- `update` edits the existing goal in place and preserves counters.
- `replace` clears any existing goal, then creates a fresh one.
- `clear` removes the goal.
- Goal writes change persisted state; they do not guarantee the worker will run.

Valid statuses are `active`, `paused`, `blocked`, `budgetLimited`,
`usageLimited`, and `complete`.

## Patterns

For a new assignment, use `replace` so usage and time counters start fresh:

```sh
codex-goalctl replace THREAD_ID "objective text"
```

If the worker should act immediately, send a normal input message after the
goal write:

```text
A goal was assigned. Call get_goal and proceed.
```

Use `codex-wakectl send` when the worker is app-server-backed.

Inspect state:

```sh
codex-goalctl get THREAD_ID
```

Edit an existing goal while preserving counters:

```sh
codex-goalctl update THREAD_ID "reworded objective"
codex-goalctl update THREAD_ID --status active
codex-goalctl update THREAD_ID --token-budget 50000
```

Clear a goal:

```sh
codex-goalctl clear THREAD_ID
```

Use `--json` when another script or tool will parse output.

## References

- Read `references/goal-lifecycle.md` when reset semantics, status changes,
  token budgets, objective limits, or text/JSON output behavior matter.
- Read `references/app-server-boundaries.md` when app-server transport, thread
  id reachability, or wake boundaries matter.
- Read `references/coordination-principles.md` when deciding how goal state
  composes with native controls, live wakes, or transcript coverage.
- Read `references/coordination-recipes.md` for command combinations involving
  durable goals, wakes, coverage, native subagents, or external managers.
- Read `references/operational-caveats.md` when concurrent writes, wake
  reliability, or cross-surface consistency matters.

## Conventions

- Use `replace` for new assignments.
- Use `update` for edits that should preserve counters.
- Do not assume goal writes wake a worker; send a follow-up message when it
  should act now.
- Prefer a short, direct wake message that tells the worker to call `get_goal`.
- Keep goal text as the durable assignment; keep wake text as a small prompt to
  look at that assignment.
- Keep the distinction clear: `codex-goalctl` provides primitives; this skill
  chooses an orchestrator workflow.
