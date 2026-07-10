# Runtime Semantics

This reference explains how `codex-wakectl` evaluates conditions, delivers
input, and persists its queue.

## Wakeability

A thread id is not enough to receive input. The target must be loaded on the
selected app-server endpoint. `CODEX_THREAD_ID` identifies the current thread,
but does not prove that it is wakeable.

Use `--endpoint` when the shared server is not the default `unix://`. A queued
job stores an absolute Unix socket path so a later runner does not reinterpret
it under another cwd or `CODEX_HOME`.

If the server is down, the endpoint changed, or the target is not loaded,
queued jobs remain pending. Immediate `send` reports the failure directly.

## Conditions

Immediate sends are not queued. They check the target's loaded and active state,
then submit a normal input turn.

If the target is active, delivery is refused unless `--allow-active` is set.
With that option, current Codex app-server behavior queues input behind an
active regular turn. Review and compaction turns are not steerable this way.

Queued conditions are polling-backed. Time conditions fire when a runner first
observes that their time has passed; they are not exact timers.

Goal predicates use AND semantics. A job fires only when every specified
status, token, and time predicate matches. `--tokens-left-lte` requires a goal
token budget. Token predicates read the goal's cumulative `tokensUsed` counter,
not current context-window usage.

Stop conditions use materialized turn history. At creation, the job records the
newest turn id and status. It fires when that turn becomes terminal or a newer
turn reaches `completed`, `interrupted`, or `failed`, including a turn that
starts and finishes between runner passes.

Command conditions retain argv and creation cwd, but execute in the runner's
environment. The wakectl timeout also bounds the command. Predicates may run
many times, so keep them cheap and repeatable. A transient success between
runner passes is not observed; keep the condition true until handled.

## Repeats

Goal milestone predicates repeat by default. The current bucket is seeded when
the job is created, so old milestones do not fire immediately. If usage crosses
several buckets between passes, one wake is sent and the cursor advances to the
newest bucket.

Repeating goal jobs remember the watched goal's creation time. A replacement
goal or lower counters rebase the stored bucket without firing.

Stop wakes repeat only with `--repeat`. Multiple completed turns between passes
are coalesced into one wake and the cursor advances to the newest observed
turn. Use `--max-fires N` when a repeating job should end by itself.

## Delivery

Wakes are ordinary user input in the target thread. They continue its existing
context and remain in its transcript.

Queued delivery is at-least-once. A wake can arrive late, retry after a failed
send, duplicate if a runner crashes after delivery, or become redundant after
manual handling.

By default, queued wakes send only to idle targets. An active or not-loaded
target defers delivery and leaves the job pending. Use `--allow-active` only for
input that remains valid while the current turn continues.

`systemError`, connection, predicate, database, and other operational failures
also leave jobs pending, but make that `run` invocation exit nonzero and record
`lastError`.

## State

Wake jobs are stored in SQLite under:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.sqlite3
```

or `~/.local/state/codex-wakectl/jobs.sqlite3` when `XDG_STATE_HOME` is unset.
Override it with `--state PATH`.

The default database is shared by all workflows using the same host user and
state path. `run` claims pending jobs before evaluating them; expired claims can
be retried after a crashed process. `cancel` changes pending jobs only, while
`list --all` retains fired and canceled rows as history.

The systemd timer is the canonical recurring runner on hosts with user systemd.
Its fixed unit names process one state database at a time. Installing it again
with another `--state` replaces that configuration; additional databases need a
scheduler managed by the caller.
