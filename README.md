# codex-goalctl

Small Unix-style CLI for reading and mutating Codex thread goals through
`codex app-server`.

This is an opinionated helper for a Codex orchestrator workflow. It is not an
official Codex interface and does not try to cover every possible goal-management
style.

The intended model is:

- A main Codex thread acts as the orchestrator.
- Subagents are treated as worker threads with persistent goal state.
- A fresh assignment should reset goal counters.
- Editing status or wording can preserve counters when that is intentional.

## Install

```sh
pipx install .
# or
uv tool install .
```

## Usage

```sh
codex-goalctl get THREAD_ID
codex-goalctl update THREAD_ID "same goal, new wording"
codex-goalctl update THREAD_ID --status paused
codex-goalctl update THREAD_ID --status blocked
codex-goalctl replace THREAD_ID "fresh goal with reset counters"
codex-goalctl replace THREAD_ID - < goal.txt
codex-goalctl replace THREAD_ID "finish report" --token-budget 50000
codex-goalctl clear THREAD_ID
```

`update` mutates the existing goal in place and preserves counters. `replace`
clears any existing goal before creating the new one, so usage counters start
fresh.

For this workflow, `replace` is the canonical command for assigning a new task
to a subagent. Use `update` when you specifically want to preserve the existing
goal's usage and time counters.

## Waking Agents

`codex-goalctl` does not wake or message a thread. It only reads and writes the
persisted goal state.

For CLI-spawned subagents, send a normal follow-up message when you want the
agent to act on a newly assigned goal:

```text
A goal was assigned. Call get_goal and proceed.
```

Use `--json` for machine-readable output.

For v1 Codex subagents, the `spawn_agent` result's `agent_id` is the thread id.

## Codex Skill

This workflow can be wrapped in a Codex skill for a main orchestrator thread.
The skill should be treated as a local operating convention: it teaches Codex
when to use `replace`, when to use `update`, and when to send a normal wake
message after changing a goal.

The skill should be narrowly scoped to orchestrator use. Installing it does not
make goal writes wake subagents, and it does not make the workflow universal for
all Codex sessions.
