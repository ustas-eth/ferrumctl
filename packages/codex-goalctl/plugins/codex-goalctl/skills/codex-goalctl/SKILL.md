---
name: codex-goalctl
description: Use when acting as a main Codex orchestrator that manages other Codex CLI threads or subagents with the host codex-goalctl command, including requests to spawn a subagent and assign it a goal. Provides workflow guidance for assigning fresh goals, editing existing goals, checking state, clearing goals, and sending a wake message after goal changes. Do not use for ordinary worker-thread tasks.
---

# Codex Goalctl

## Purpose

Use this skill when the current Codex session coordinates other Codex CLI
threads and needs to manage their persisted goal state.

Assume `codex-goalctl` is installed on the host. It reads and writes goal state
through `codex app-server`; it does not send chat messages or reliably wake a
CLI-owned thread.

## Workflow

1. Identify or create the target thread. For v1 Codex subagents, the
   `spawn_agent` result's `agent_id` is the thread id.

2. For a new assignment, replace the goal so counters start fresh:

```sh
codex-goalctl replace THREAD_ID "objective text"
```

3. If the worker should act immediately, send a normal input message:

```text
A goal was assigned. Call get_goal and proceed.
```

Use `codex-wakectl send` when the worker is app-server-backed.

4. Inspect or edit state when needed:

```sh
codex-goalctl get THREAD_ID
codex-goalctl update THREAD_ID "reworded objective"
codex-goalctl update THREAD_ID --status active
codex-goalctl clear THREAD_ID
```

Use `--json` when another script or tool will parse output.

## References

- Read `references/goal-lifecycle.md` when reset semantics, status changes,
  token budgets, or wake behavior matter.
- Read `references/orchestrator-worker-loop.md` when combining goal assignment
  with wakes or read coverage.

## Rules

- Use `replace` for new assignments.
- Use `update` for edits that should preserve counters.
- Do not assume goal writes wake a subagent; send a follow-up message.
- Keep the distinction clear: `codex-goalctl` provides primitives; this skill
  chooses an orchestrator workflow.
