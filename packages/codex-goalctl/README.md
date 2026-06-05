# codex-goalctl

`codex-goalctl` reads and changes persisted Codex thread goals through
`codex app-server`.

Use it from scripts or orchestrator sessions that already know the target
thread id. It does not start agents, send chat messages, or wake sleeping
threads.

## Install

```sh
uv tool install .
```

## Usage

```sh
codex-goalctl get THREAD_ID
codex-goalctl update THREAD_ID "same goal, new wording"
codex-goalctl update THREAD_ID --status paused
codex-goalctl replace THREAD_ID "fresh goal with reset counters"
codex-goalctl clear THREAD_ID
```

`replace` starts a fresh goal. `update` edits the existing goal in place. Use
`--json` when another program will parse output.

Goal writes do not wake a thread. Send a normal follow-up message when a worker
should act immediately:

```text
A goal was assigned. Call get_goal and proceed.
```

More detail: [docs/goal-lifecycle.md](docs/goal-lifecycle.md).

## Codex Skill

This package includes an optional Codex skill for orchestrator threads:

```text
plugins/codex-goalctl/skills/codex-goalctl/SKILL.md
```

Install it from the `ferrumctl` root marketplace:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-goalctl@ferrumctl
```

The skill is optional. It explains one workflow for assigning goals to other
Codex threads; it does not change CLI behavior.

## Example

The screenshot below shows a main Codex thread using the skill, spawning a
subagent, assigning a persisted goal, waking the subagent, and receiving the
completed status back.

<p align="center">
  <img src="docs/assets/codex-goalctl-smoke.png" alt="Codex goalctl smoke test" width="900">
</p>
