# Runtime Semantics

This reference explains how `codex-wakectl` evaluates conditions, delivers
events or input, and persists its queue.

## Wakeability

A thread id is not enough to receive a wake. The target must normally be loaded
on the selected app-server endpoint. `CODEX_THREAD_ID` identifies the current
thread, but does not prove that it is wakeable. An event job with `--resume`
may load an unloaded target explicitly.

Use `--endpoint` when the shared server is not the default `unix://`. A queued
job stores an absolute Unix socket path so a later runner does not reinterpret
it under another cwd or `CODEX_HOME`.

If the server is down or the endpoint changed, queued jobs remain pending. An
unloaded target also remains pending unless its event action permits resume.

Codex rejects direct app-server input to parent-owned agents. They can be the
subject of goal or stop conditions, but a scheduled wake must target the root
thread (`/root`) or another thread that accepts direct lifecycle control. A
nested native parent may itself be parent-owned.

Wakectl accepts canonical task names beginning with `/root` for condition
subjects and delivery targets. `CODEX_THREAD_ID` supplies the tree scope, or
`--tree THREAD_ID` can name any member of the intended tree. Task names are
resolved during job creation and the thread ids are stored, so later name reuse
does not retarget a job. A parent-owned child is rejected as a delivery target
when selected by canonical task name. If the same child is passed as a raw
thread id, a later native direct-input rejection makes the job `failed` rather
than leaving it pending forever.

## Synchronous Waiting

`wait` evaluates a condition in the invoking process. It keeps any condition
cursor only in memory and does not create a SQLite job, involve the runner, or
send an event or input. Its completion is an ordinary process result, not a
callback into a Codex thread.

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

Stop conditions use materialized turn history. Without `--turn`, creation
records the newest turn id and status as a boundary. The condition fires when
that turn becomes terminal or a newer turn reaches `completed`, `interrupted`,
or `failed`, including a turn that starts and finishes between later runner
passes. A turn already terminal when the boundary is recorded does not fire the
condition.

If no turn existed when the watch was created, the first later terminal turn
is treated as the observed completion.

`--turn TURN_ID` binds a one-shot condition to that exact turn. It becomes ready
if the turn is already terminal and otherwise waits for that turn to stop.
`--turn latest` resolves to the newest existing turn during creation; it fails
when the thread has no turns. Exact-turn conditions cannot repeat.

The runner pages history until it finds the stored boundary or exact turn. If
rollback, compaction, or another history change removes that identity, the job
becomes `failed`; older terminal turns are not treated as new evidence.

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
turn. Use `--max-fires N` when a repeating job should end by itself. An exact
`--turn` watch is always one-shot.

## Delivery

The default action is an event wake. The runner injects a short agent message
derived from the matched condition. If the target is idle, it then submits an
empty `turn/start`, which runs the model with existing context without adding a
user message. Both the event and resulting response remain in thread history.

The generated text begins with `Scheduled event JOB/FIRE`, and each event has a
stable `lastEventItemId`. A repeating job uses the same job id and increments
the fire number.

By default, an active or unloaded target defers event delivery. With
`--notify-active`, an active target receives the agent event and no new turn is
started. With `--resume`, an unloaded target is loaded; an active persisted goal
can continue immediately, in which case the event enters that active turn.

Event injection and empty turn start are separate requests. If another turn
wins the idle race after injection, the event enters that active work and the
job records `eventNotifiedActive`. If event acceptance or the following wake
cannot be established safely, the job becomes `uncertain` and retains the
event item id for reconciliation.

`--input MESSAGE` selects the ordinary input action. It waits for an idle
target, submits native `turn/start`, and confirms the client message in
materialized history. Delayed input does not support active steering or resume;
use immediate thread control for those decisions. Pending jobs created by
earlier wakectl releases preserve their original input and `--allow-active`
semantics.

Queued delivery is at-least-once. An event or input can arrive late, duplicate
if a runner stops after delivery, or become redundant after manual handling.
An uncertain job is not retried automatically because its action may already
have taken effect.

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

Version 0.5 adds a structured action to each job. Existing rows without that
field decode as legacy input actions; upgrading does not reinterpret their
stored messages as event wakes.

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
