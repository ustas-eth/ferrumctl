# codex-goalctl

`codex-goalctl` is a small command-line tool for reading and changing Codex
thread goals through `codex app-server`.

It is meant for scripts and orchestrator sessions that already know the target
thread id. The command only reads and writes goal state; it does not start
agents, send chat messages, or wake sleeping threads.

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

`get` prints the current goal. With `--json`, it prints a machine-readable
response.

`update` changes an existing goal in place. Use it for status changes, budget
changes, or objective edits where the existing usage and time counters should be
preserved.

`replace` clears any existing goal before creating the new one. Use it when a
new assignment should start with fresh counters.

`clear` removes the current goal from the thread.

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

This repo includes an optional Codex plugin with an explicit-only skill for
main-thread orchestration:

```text
plugins/codex-goalctl/skills/codex-goalctl/SKILL.md
```

The repo also includes a marketplace manifest:

```text
.agents/plugins/marketplace.json
```

Install it from the GitHub marketplace source with:

```sh
codex plugin marketplace add ustas-eth/codex-goalctl
codex plugin add codex-goalctl@codex-goalctl
```

The skill documents one workflow for coordinating subagents from a main Codex
thread: use `replace` for new assignments, use `update` for in-place edits, and
send a normal follow-up message when the subagent should act immediately.

The skill is optional. Installing it does not change the CLI behavior and does
not make goal writes wake subagents.
