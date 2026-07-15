# codex-wakectl

`codex-wakectl` schedules durable input for Codex threads after later conditions
through a shared `codex app-server`.

Use `add` to persist a wake that a runner will deliver later. The secondary
`wait` interface polls synchronously for scripts: it blocks only its invoking
process, sends no input, and persists no job. Immediate input, inspection, and
interruption belong to `codex-threadctl`.

Wakectl 0.3 moves its former `loaded`, `status`, `inspect`, and `interrupt`
commands, along with immediate `send`, to that package.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-wakectl
```

From this package directory:

```sh
uv tool install .
```

## Setup

Run one app-server, then start or resume Codex sessions through it:

```sh
codex app-server --listen unix://
codex --remote unix://
```

Only threads loaded on that endpoint can receive input. When
`codex-threadctl` is installed, `codex-threadctl loaded` lists them.

## Examples

Wake this thread later:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 10m --to "$SELF" "Time check."
```

Wake a coordinator when a goal or later turn ends:

```sh
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited --to ORCH "Worker goal reached a terminal status."
codex-wakectl add stop WORKER --to ORCH "Worker turn ended."
```

Wake when a host-visible condition becomes true:

```sh
codex-wakectl add cmd --to THREAD_ID "Input is ready." -- sh -c 'test -f done.txt'
```

Synchronously gate a script on a Codex condition:

```sh
codex-wakectl wait stop WORKER --max-wait 30m
```

Process queued jobs once, or install the recurring user timer:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
```

By default, wakectl starts input only when the target appears idle. With
`--allow-active`, it uses native turn-scoped steering when a regular turn is
active. The default queue is shared for the host user; keep job ids and cancel
only jobs your workflow owns.

More detail:

- [docs/runtime-semantics.md](docs/runtime-semantics.md)
- [docs/coordination-practices.md](docs/coordination-practices.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-wakectl@ferrumctl
```

The skill lives at `plugins/codex-wakectl/skills/codex-wakectl/SKILL.md`.
It does not make non-app-server sessions wakeable.
