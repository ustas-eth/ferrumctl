# codex-wakectl

`codex-wakectl` sends and schedules normal input turns for Codex threads loaded
on a shared `codex app-server`.

Use it for self-reminders, worker completion notifications, peer handoffs, and
long waits that should resume a thread later. It does not start Codex sessions
or inject terminal input.

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

Run one app-server, then start or resume Codex sessions through it.

```sh
codex app-server --listen unix://
codex --remote unix://
codex-wakectl loaded
```

For daily use, keep the Codex flags you normally use and add `--remote
unix://` to that command or shell shortcut:

```sh
alias x='codex --remote unix://'
```

Only loaded app-server threads can be woken. `codex-wakectl loaded` is the
quick check.

## Examples

Send a turn now:

```sh
codex-wakectl send THREAD_ID "Check your goal and continue if useful."
```

Wake this thread later:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 10m --to "$SELF" "Wake up and check status."
```

Wake a coordinator when a worker stops:

```sh
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited --to ORCH "Worker goal stopped."
codex-wakectl add stop WORKER --to ORCH "Worker stopped. Inspect it."
```

Wake a thread when a host-visible condition becomes true:

```sh
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

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-wakectl@ferrumctl
```

The skill lives at `plugins/codex-wakectl/skills/codex-wakectl/SKILL.md`.
It does not make non-app-server sessions wakeable.
