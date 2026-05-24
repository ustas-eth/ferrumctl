# codex-goalctl

Small Unix-style CLI for reading and mutating Codex thread goals through
`codex app-server`.

The CLI is intentionally small and policy-neutral. It exposes goal operations;
it does not decide how a Codex orchestrator should use them.

The bundled Codex skill is different: it is an opinionated workflow for one
orchestrator style. That workflow assumes:

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

`update` sends a direct goal mutation. When a goal already exists, it preserves
that goal's usage and time counters.

`replace` is a convenience command that clears any existing goal before creating
the new one, so usage counters start fresh.

The command itself does not make `replace` canonical. The bundled Codex skill
does, because that skill defines a specific orchestrator workflow where a new
subagent assignment should reset counters.

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

## Opinionated Codex Skill

This repo includes a Codex plugin with an explicit-only orchestrator skill:

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

The skill is the opinionated part of this repo. It is a local operating
convention that teaches Codex when to use `replace`, when to use `update`, and
when to send a normal wake message after changing a goal.

The skill should be narrowly scoped to orchestrator use. Installing it does not
make goal writes wake subagents, and it does not make the workflow universal for
all Codex sessions.
