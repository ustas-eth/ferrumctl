---
name: codex-goalctl
description: Use when acting as a main Codex orchestrator that manages other Codex CLI threads or subagents with the host codex-goalctl command, including requests to spawn a subagent and assign it a goal. Provides workflow guidance for assigning fresh goals, editing existing goals, checking state, clearing goals, and sending a wake message after goal changes. Do not use for ordinary worker-thread tasks.
---

# Codex Goalctl

## Purpose

Use this skill when the current Codex session is coordinating other Codex CLI
threads and needs to manage their goal state.

`codex-goalctl` is the host command that reads and writes persisted goal state
through `codex app-server`. This skill describes a main-thread workflow on top
of that command.

Assume `codex-goalctl` is already installed on the host. It does not send chat
messages and does not reliably wake a CLI-owned thread.

## Workflow

1. Identify or create the target thread.
   For v1 Codex subagents, the `spawn_agent` result's `agent_id` is the thread id.

2. For a new assignment, reset counters by replacing the goal:

```sh
codex-goalctl replace THREAD_ID "objective text"
```

3. If the subagent should act immediately, send it a normal input message:

```text
A goal was assigned. Call get_goal and proceed.
```

4. Inspect goal state when needed:

```sh
codex-goalctl get THREAD_ID
```

5. Edit an existing goal in place when counters should be preserved:

```sh
codex-goalctl update THREAD_ID "reworded objective"
codex-goalctl update THREAD_ID --status active
codex-goalctl update THREAD_ID --status paused
codex-goalctl update THREAD_ID --status blocked
```

6. Clear a goal when the thread should have no persisted objective:

```sh
codex-goalctl clear THREAD_ID
```

Use `--json` when another script or tool will parse the output.

## Rules

- Use `replace` for new assignments, because it resets usage and time counters.
- Treat `replace` as clear-then-set. If preserving the current goal on failure
  matters more than resetting counters, use `update`.
- Use `update` for status changes, budget changes, and objective edits that
  should preserve counters.
- Do not assume goal writes wake a subagent; send a normal follow-up message.
- Keep the distinction clear: `codex-goalctl` provides goal operations; this
  skill chooses a workflow for orchestrator sessions.
