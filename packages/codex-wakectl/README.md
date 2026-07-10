# codex-wakectl

`codex-wakectl` sends and schedules input for Codex threads through a shared
`codex app-server`.

Use it to deliver input now, wait for a Codex condition, or persist a wake that
a runner will deliver later. Thread inspection, interruption, and compaction
belong to `codex-threadctl`.

Wakectl 0.3 moves its former `loaded`, `status`, `inspect`, and `interrupt`
commands to that package; `compact` is introduced there.

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

Send input now:

```sh
codex-wakectl send THREAD_ID "Check your goal and continue if useful."
```

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

Block until a condition without sending input:

```sh
codex-wakectl wait stop WORKER --max-wait 30m
```

Process queued jobs once, or install the recurring user timer:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
```

By default, wakectl sends only to idle targets. Use `--allow-active` only for
input that remains safe while the current turn continues. The default queue is
shared for the host user; keep job ids and cancel only jobs your workflow owns.

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
