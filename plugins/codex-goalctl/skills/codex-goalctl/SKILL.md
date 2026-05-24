---
name: codex-goalctl
description: Use only when acting as a main Codex orchestrator that manages other Codex CLI threads or subagents with the host codex-goalctl command. This is an opinionated workflow for assigning, updating, inspecting, clearing, and waking subagent goals; do not use for ordinary worker-thread tasks.
---

# Codex Goalctl

## Purpose

Use this skill when the current Codex session is the orchestrator and needs to
manage goal state for other Codex CLI threads. This is a local workflow
convention, not an official Codex control API.

Assume `codex-goalctl` is already installed on the host. It writes persisted
goal state through `codex app-server`; it does not send chat messages and does
not reliably wake a CLI-owned thread.

## Workflow

1. Identify the target thread id.
   For v1 Codex subagents, the `spawn_agent` result's `agent_id` is the thread id.

2. Assign a new task with fresh counters:

```sh
codex-goalctl replace THREAD_ID "objective text"
```

3. Wake the subagent only when you want it to act immediately by sending a
normal input message to that subagent:

```text
A goal was assigned. Call get_goal and proceed.
```

4. Inspect goal state when needed:

```sh
codex-goalctl get THREAD_ID
```

5. Preserve counters only for intentional in-place edits:

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

- Use `replace` as the canonical primitive for a fresh subagent assignment.
- Use `update` only when preserving existing usage and time counters is correct.
- Do not assume goal writes wake a subagent; send a normal follow-up message.
- Do not present this as universal Codex behavior. It is an opinionated local
  orchestration workflow built around `codex-goalctl`.
