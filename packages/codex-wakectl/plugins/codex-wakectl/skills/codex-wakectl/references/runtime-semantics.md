<!-- Generated from packages/codex-wakectl/docs/runtime-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Runtime Semantics

This reference explains how `codex-wakectl` behaves after a command has been
chosen. It is not a quickstart.

## Wakeability

A thread id is not enough to receive a wake. The target thread must be loaded on
the selected app-server endpoint. `CODEX_THREAD_ID` identifies the current Codex
thread, but it does not prove that the current thread is wakeable.

Use `--endpoint` on any command when the shared app-server is not the default
`unix://`. If the app-server is down, the endpoint changed, or the target thread
is not loaded, queued jobs stay pending and can be retried by a later runner.
When a job is created, a Unix endpoint is resolved to an absolute socket path so
the runner does not reinterpret it under a different cwd or `CODEX_HOME`.

App-server status is separate from goal status. `idle` means the thread has no
running turn at that moment. A thread with an `active` goal can still be
`idle`, especially when the goal was written externally and the thread has not
yet been prompted to observe it.

`inspect` can read persisted turns even when a thread is not loaded. Sending or
interrupting still requires the target to be loaded on the selected endpoint.

## Inspection And Interruption

`inspect` reads thread metadata, goal state, and the two newest turns through
the app-server. By default, the newest turn includes structured activity such
as agent messages, command status, file changes, searches, and tool calls. The
previous turn is a summary used to expose its agent response. Command output,
patch content, and tool results are omitted from the report.

`--brief` requests summary turns only. It avoids loading command output, patch
content, and tool results that would be discarded, so it is the faster choice
when status and recent responses are enough. `--no-previous` omits the previous
turn. `--items` limits what wakectl prints after loading the newest turn; it does
not reduce the full turn transferred by the app-server.

Persisted turns provide start and completion timestamps in whole seconds and a
duration in milliseconds when known. Completed command, MCP, and dynamic tool
items can also provide durations. Codex rounds those durations down to whole
milliseconds, so text output renders a native `0` as `<1ms`; JSON preserves the
numeric value. Sleep items report their requested interval as `requested`, not
measured elapsed time.

Persisted turn items do not provide absolute timestamps. Live item
notifications do, but they are delivered only to clients connected when the
activity occurs and are not replayed to a later `inspect` process. Inspection
therefore reports available turn boundary timestamps and item durations without
inventing item times.

The report is assembled from several app-server requests rather than one atomic
snapshot. A running thread can advance while it is being inspected. Wakectl
fetches a final turn summary and lifecycle state after any full-turn load; if a
new turn appeared or its lifecycle changed, that summary is reported instead of
combining stale activity with newer state. The turn line identifies the selected
item view as `full` or `summary`.

Inspection and durable stop watches use the experimental
`thread/turns/list` method available in Codex 0.144 and compatible releases.

`interrupt` discovers the active turn id and sends `turn/interrupt` with that id
as a precondition. If the active turn changes before the request is accepted,
Codex rejects the request instead of interrupting a different turn. The command
returns after Codex reports the interruption.

## Conditions

Immediate sends are not queued. They check that the target is loaded and idle,
then submit a wake.

If the target is active, the send fails unless `--allow-active` is set. With
`--allow-active`, wakectl skips its idle-target guard and asks Codex to accept
the input anyway. In current Codex app-server behavior, input sent to an active
regular turn is added to that turn's pending input queue. Review and compaction
turns are not steerable this way.

Queued conditions are evaluated by a runner. Time conditions are not exact
timers; they fire when a runner observes that the scheduled time has passed.

Goal predicates are combined with AND semantics. A job fires only when every
specified status, token, and time predicate matches. `--tokens-left-lte`
requires the watched goal to have a token budget. Token predicates read the
goal's persisted `tokensUsed` counter, not context-window usage.

Stop conditions use persisted turn history. At creation, the job records the
newest turn id and status. It fires when that turn becomes terminal or a newer
turn reaches `completed`, `interrupted`, or `failed`. A turn can therefore start
and finish between runner passes without being missed.

Command conditions run from the directory where the job was created. The wakectl
timeout also bounds the predicate command. Queued command predicates may run
more than once before they become ready, so keep them cheap and safe to repeat.
They inherit the runner's environment, not the environment of the process that
created the job. This matters when the runner is a systemd service. A transient
success between runner passes is not observed; keep the predicate true until it
is handled.

## Repeats

Goal milestone predicates repeat by default. They fire once when a later bucket
is observed. If usage jumps across several buckets between runner passes,
wakectl sends one wake and records the newest bucket; it does not send catch-up
wakes for every skipped bucket. The current bucket is seeded at job creation, so
old milestones do not fire immediately.

Repeating goal jobs remember the watched goal's creation time. When a later
goal is observed, the stored bucket rebases without firing. Counter decreases
also rebase older jobs that do not yet have that marker.

Stop wakes repeat only with `--repeat`. If several turns finish between runner
passes, one wake is sent and the cursor advances to the newest observed turn.
Use `--max-fires N` when a repeating job should stop by itself.

## Delivery

Queued wakes are polling-backed input turns. They may run late, retry after a
failed send, or become redundant if the target or supervisor already handled the
result.

Delivery is at-least-once: if a runner sends a wake and then crashes before it
records the result, a later runner can send the same job again.

By default, queued wakes send only to idle target threads. Use `--allow-active`
only for messages that are safe to deliver while the target keeps running. For
checkpoints, let the target stop first so the answer can be inspected before
work continues.

An active or not-loaded target defers delivery and leaves the job pending.
`systemError`, connection, predicate, database, and other operational errors
also leave the job pending, but make that `run` invocation exit nonzero and
record `lastError`.

## State

Wake jobs are stored in SQLite under:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.sqlite3
```

or `~/.local/state/codex-wakectl/jobs.sqlite3` when `XDG_STATE_HOME` is unset.
Override with `--state PATH`.

The default state file is shared by all workflows using the same host user and
state path. Jobs from unrelated agents, projects, and target threads may appear
in the same list. `--state PATH` selects a different queue.

`codex-wakectl run` claims pending jobs before evaluating them. Claims expire so
another runner can retry after a crashed process.

`cancel` changes pending jobs only. Fired and canceled rows remain historical
records visible through `list --all`.

The systemd timer is the canonical recurring runner on hosts with user systemd.
Its fixed user-unit names process one state database at a time; installing it
again with another `--state` replaces that configuration. Run additional state
databases from schedulers you manage. On hosts without user systemd, run
`codex-wakectl run` from the scheduler already in use.
