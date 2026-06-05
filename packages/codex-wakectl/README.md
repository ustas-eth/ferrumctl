# codex-wakectl

`codex-wakectl` wakes Codex threads connected to a running `codex app-server`.

Use it to send a turn now, or to queue a wake for a time, goal state, thread
stop, or shell predicate. It does not start Codex sessions or inject terminal
input.

## Install

```sh
uv tool install .
```

## Setup

```sh
codex app-server --listen unix://
codex --remote unix://
codex-wakectl loaded
```

Only loaded app-server threads can be woken.

## Usage

```sh
codex-wakectl send THREAD_ID "Check your goal and continue if useful."
codex-wakectl add time --after 10m --to THREAD_ID "Wake up and check status."
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited --to ORCH "Worker goal stopped."
codex-wakectl add stop WORKER --to ORCH "Worker stopped. Inspect it."
codex-wakectl add cmd --to THREAD_ID "Predicate is true." -- sh -c 'test -f done.txt'
```

Process queued jobs with `codex-wakectl run`, or install the user timer:

```sh
codex-wakectl systemd install --interval 30s
```

By default, wakes refuse to start a turn while the target thread is active. Use
`--allow-active` only when overlapping turns are intentional.

More detail:

- [docs/runtime-semantics.md](docs/runtime-semantics.md)
- [docs/coordination-practices.md](docs/coordination-practices.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)

## Codex Skill

This package includes an optional Codex skill for wake scheduling:

```text
plugins/codex-wakectl/skills/codex-wakectl/SKILL.md
```

Install it from the `ferrumctl` root marketplace:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-wakectl@ferrumctl
```

The skill is optional. It explains app-server wake patterns; it does not change
CLI behavior or make non-app-server sessions wakeable.
