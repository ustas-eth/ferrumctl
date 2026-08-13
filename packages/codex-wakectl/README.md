# codex-wakectl

`codex-wakectl` schedules durable thread attention after later conditions
through a shared `codex app-server`.

Use `add` to persist a condition and wake action for later runner delivery. A
normal wake adds a short scheduled event to agent context and starts an empty
turn when the target is idle. It does not add a user message.

The secondary `wait` interface polls synchronously for scripts: it blocks only
its invoking process, sends no event or input, and persists no job. Immediate
control belongs to `codex-threadctl`.

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

Wake this thread later or return a coordinator's attention after worker
progress:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 10m --to "$SELF"
codex-wakectl add goal WORKER --status complete,blocked,budgetLimited,usageLimited \
  --to ORCH
codex-wakectl add stop WORKER --to ORCH
```

In a native subagent tree with canonical task names, a child can be watched
while delivery returns to the native parent:

```sh
codex-wakectl add goal /root/reviewer --status complete,blocked \
  --to /root
```

`CODEX_THREAD_ID` scopes the task names; pass `--tree THREAD_ID` when needed.
Jobs store the resolved thread ids. Parent-owned children cannot be delivery
targets.

An unqualified stop watch observes a completion after its creation boundary.
When one particular turn is the target, use `--turn TURN_ID`; `--turn latest`
explicitly binds the newest existing turn even if it has already ended.

Host-visible conditions can also schedule a wake:

```sh
codex-wakectl add cmd --to THREAD_ID -- test -f done.txt
```

By default, a ready event waits for the target to become idle. Use
`--notify-active` when the event remains useful during current work. Use
`--resume` only when wakectl should load an unloaded target; resuming a thread
with an active goal can continue that goal immediately.

Schedule ordinary input only when its text is deliberately the instruction:

```sh
codex-wakectl add cmd --to THREAD_ID \
  --input "Continue from done.txt and complete the next step." -- \
  test -f done.txt
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

Scheduled events are short agent-context items, not user instructions. They
still remain in thread history and can be delayed or duplicated. Explicit
`--input` waits for an idle target and uses the ordinary confirmed input path.

The queue is shared by the host user, so retain job ids and cancel only jobs
your workflow owns.

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
