# codex-goalctl

Small Unix-style CLI for reading and mutating Codex thread goals through
`codex app-server`.

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
