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
requires the watched goal to have a token budget.

Stop conditions are active-to-idle edges. If the watched thread is already idle
when the job is created, the job waits until the thread is observed active and
then idle again. `unknown` status is not treated as active or stopped.

Command conditions run from the directory where the job was created. The wakectl
timeout also bounds the predicate command. Queued command predicates may run
more than once before they become ready, so keep them cheap and safe to repeat.

## Repeats

Goal milestone predicates repeat by default. They fire once when a later bucket
is observed. If usage jumps across several buckets between runner passes,
wakectl sends one wake and records the newest bucket; it does not send catch-up
wakes for every skipped bucket. The current bucket is seeded at job creation, so
old milestones do not fire immediately.

Stop notifications repeat only with `--repeat`. Use `--max-fires N` when a
repeating job should stop by itself.

## Delivery

Queued wakes are polling-backed notifications. They may run late, retry after a
failed send, or become redundant if the target or supervisor already handled the
result.

Delivery is at-least-once: if a runner sends a wake and then crashes before it
records the result, a later runner can send the same job again.

By default, queued wakes send only to idle target threads. Use `--allow-active`
only for messages that are safe to deliver while the target keeps running. For
checkpoints, let the target stop first so the answer can be inspected before
work continues.

## State

Wake jobs are stored in SQLite under:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.sqlite3
```

or `~/.local/state/codex-wakectl/jobs.sqlite3` when `XDG_STATE_HOME` is unset.
Override with `--state PATH`.

`codex-wakectl run` claims pending jobs before evaluating them. Claims expire so
another runner can retry after a crashed process.

The systemd timer is the canonical recurring runner on hosts with user systemd.
On other hosts, run `codex-wakectl run` from the scheduler you already use.
