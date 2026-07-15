<!-- Generated from packages/codex-wakectl/docs/runtime-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

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
queued jobs remain pending.

Codex rejects direct app-server input to v2 subagents. Schedule those through
their native parent instead of using them as wake targets.

## Synchronous Waiting

`wait` evaluates a condition in the invoking process. It keeps any condition
cursor only in memory and does not create a SQLite job, involve the runner, or
send input. Its completion is an ordinary process result, not a callback into a
Codex thread.

This mode is useful when a script needs an exit status from Codex goal or turn
state. A caller that already owns a live subagent or terminal handle can wait on
that handle directly. Wrapping an existing process with `wait cmd` only adds a
second polling process.

## Conditions

Synchronous waits and queued conditions are polling-backed. Queued time
conditions fire when a runner first observes that their time has passed; they
are not exact timers.

Goal predicates use AND semantics. A job fires only when every specified
status, token, and time predicate matches. `--tokens-left-lte` requires a goal
token budget. Token predicates read the goal's cumulative `tokensUsed` counter,
not current context-window usage.

A goal watch records the goal creation time visible when it is created. If that
assignment is replaced, the job becomes `superseded` rather than firing for the
replacement. If no goal exists at creation, the watch binds to the first one it
observes later.

Codex exposes goal creation time at one-second resolution. Two assignments
created in the same second can be indistinguishable to a polling watcher.

Stop conditions use materialized turn history. At creation, the job records the
newest turn id and status. It fires when that turn becomes terminal or a newer
turn reaches `completed`, `interrupted`, or `failed`, including a turn that
starts and finishes between runner passes.

If no turn existed when the watch was created, the first later terminal turn
is treated as the observed completion.

The runner pages history until it finds the stored turn cursor. If rollback,
compaction, or another history change removes that cursor, the job becomes
`failed`; older terminal turns are not treated as new evidence.

Command conditions retain argv and creation cwd, but execute in the runner's
environment. The wakectl timeout also bounds the command. Predicates may run
many times. Standard input reads from `/dev/null`, standard output and standard
error are discarded, and only exit status or timeout is retained. A transient
success between runner passes is not observed; keep the condition true until
handled.

## Repeats

Goal milestone predicates repeat by default. The current bucket is seeded when
the job is created, so old milestones do not fire immediately. If usage crosses
several buckets between passes, one wake is sent and the cursor advances to the
newest bucket.

Lower usage counters rebase a repeating milestone without firing. A replacement
goal supersedes the entire watch.

Stop wakes repeat only with `--repeat`. Multiple completed turns between passes
are coalesced into one wake and the cursor advances to the newest observed
turn. Use `--max-fires N` when a repeating job should end by itself.

## Delivery

Wakes are ordinary user input in the target thread. They continue its existing
context and remain in its transcript.

Queued delivery is at-least-once. A wake can arrive late, duplicate if a runner
crashes after delivery, or become redundant after manual handling.

By default, queued wakes send only to idle targets. An active or not-loaded
target defers delivery and leaves the job pending. The runner confirms the
client message in materialized history before recording a new turn as fired.
The idle check and native start request are not atomic; if another regular turn
wins that race, the recorded delivery mode is `steered`.

With `--allow-active`, the runner obtains the current active turn id and uses
native `turn/steer` with that expected id. A stale id, review turn, or compaction
turn is rejected instead of steering a replacement turn.

If the outcome of a submitted start or steer request cannot be confirmed, the
job becomes `uncertain`. It is not retried automatically because the input may
already have been delivered.

The runner does not answer approval or user-input requests raised by the
resulting turn. A capable app-server client must remain available to resolve
them.

RPC, connection, predicate, database, and other operational failures also leave
jobs pending, but make that `run` invocation exit nonzero and record
`lastError`.

## State

Wake jobs are stored in SQLite under:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.sqlite3
```

or `~/.local/state/codex-wakectl/jobs.sqlite3` when `XDG_STATE_HOME` is unset.
Override it with `--state PATH`.

The default state directory is mode `0700` and the database is mode `0600`.
Existing default state is tightened when opened. A custom `--state` file is
created as `0600`, but wakectl does not change permissions on an existing
custom file or directory.

The default database is shared by all workflows using the same host user and
state path. `run` claims pending jobs and renews each claim before condition
evaluation and delivery. Expired claims can be retried after a crashed process;
at-least-once duplicates remain possible if a process stops after delivery but
before committing the result. `cancel` changes only pending jobs without a live
claim, while `list --all` retains terminal rows as history.

The systemd timer is the canonical recurring runner on hosts with user systemd.
Its fixed unit names process one state database at a time. Installing it again
with another `--state` replaces that configuration; additional databases need a
scheduler managed by the caller.
