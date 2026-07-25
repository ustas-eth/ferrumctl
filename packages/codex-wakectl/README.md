# codex-wakectl

`codex-wakectl` schedules durable input for Codex threads after later conditions
through a shared `codex app-server`.

Use `add` to persist a wake that a runner will deliver later. The secondary
`wait` interface polls synchronously for scripts: it blocks only its invoking
process, sends no input, and persists no job. Immediate input, inspection, and
interruption belong to `codex-threadctl`.

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

Wake this thread later or wake a coordinator after worker progress:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 10m --to "$SELF" \
  "Self-scheduled reminder: Review progress."
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited \
  --to ORCH "Automated event: Worker goal reached a terminal status."
codex-wakectl add stop WORKER --to ORCH \
  "Automated event: Worker turn ended."
```

An unqualified stop watch observes a completion after its creation boundary.
When one particular turn is the target, use `--turn TURN_ID`; `--turn latest`
explicitly binds the newest existing turn even if it has already ended.

Host-visible conditions can also schedule input:

```sh
codex-wakectl add cmd --to THREAD_ID \
  "Automated event: Input is ready." -- sh -c 'test -f done.txt'
```

Use `wait` only when a script needs a synchronous exit status:

```sh
codex-wakectl wait stop WORKER --max-wait 30m
```

Process queued jobs once, or install the recurring user timer:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
```

Queued messages arrive as ordinary thread input. By default, delivery waits for
the target to appear idle; `--allow-active` permits turn-scoped steering. The
queue is shared by the host user, so retain job ids and cancel only jobs your
workflow owns.

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
