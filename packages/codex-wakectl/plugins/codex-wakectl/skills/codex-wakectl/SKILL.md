---
name: codex-wakectl
description: "Use when input must survive the current turn and reach a Codex thread after a later time, goal state, turn completion, or host condition, or when durable wake jobs and runners must be managed. Synchronous waits are only for scripts or thread-id-only controllers that need an exit status. Do not replace native polling of a live handle or use this for immediate control."
---

# Codex Wakectl

## Purpose

Use `codex-wakectl add` to persist a condition and input for later runner
delivery. The job survives the current Codex turn.

`wait` is a separate synchronous interface. It blocks only its invoking
process, creates no job, sends no input, and does not start a Codex turn when
the condition matches.

Queued input continues the target's existing conversation and remains in its
transcript. Wakectl does not inspect history for the caller, edit goals,
interrupt turns, or spawn agents.

## Choose A Primitive

Choose according to what should happen to the caller:

- Use native wait or poll when this turn owns a live subagent or terminal handle
  and should remain active.
- Use `wait goal` or `wait stop` when a script or thread-id-only controller
  needs a synchronous exit status.
- Use `add` when this turn should end and a runner should deliver input after a
  later condition.
- Use native subagent input for an immediate message. When only a thread id is
  available, use an immediate control tool only if its skill is available.

The target must already be loaded on the job's app-server endpoint when
delivery occurs. A default shared setup is:

```sh
codex app-server --listen unix://
codex --remote unix://
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

## Schedule Input

Schedule by time, goal state or usage, turn completion, or a host predicate:

```sh
codex-wakectl add time --after 30m --to "$SELF" \
  "Self-scheduled reminder: Review progress."

codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to COORDINATOR \
  "Automated event: Worker goal reached a terminal status."

codex-wakectl add goal WORKER --tokens-used-every 2000000 \
  --max-fires 4 --to COORDINATOR \
  "Automated event: Worker token milestone."

codex-wakectl add stop WORKER --turn TURN_ID --to COORDINATOR \
  "Automated event: Worker turn ended."

codex-wakectl add cmd --to "$SELF" \
  "Automated event: Input is ready." -- test -f done.txt
```

An unqualified stop watch records a boundary at creation and observes a later
terminal turn. Use `--turn TURN_ID` when one exact turn is the subject,
especially when watch creation can race completion. A goal watch binds to one
assignment; replacing that goal supersedes the watch.

Goal completion and turn completion are separate. Observe the turn boundary
when the final response matters.

## Run And Manage Jobs

Process the queue once or install the recurring user timer:

```sh
codex-wakectl run
codex-wakectl systemd install --interval 30s
codex-wakectl list
codex-wakectl cancel JOB_ID
```

Synchronously gate a script without creating a wake job:

```sh
codex-wakectl wait goal WORKER --status complete,blocked --max-wait 30m
codex-wakectl wait stop WORKER --max-wait 30m
```

Do not wrap a terminal process already owned by this turn with `wait cmd`; poll
that original process directly.

## Delivery Boundaries

- By default, ready input waits for the target to appear idle. `--allow-active`
  permits expected-turn steering only when the input remains valid during
  current work.
- The idle check and start are not atomic. Treat the recorded delivery mode as
  authoritative.
- Delivery is at-least-once. A message may be late or duplicated; an
  unconfirmed submission becomes `uncertain` instead of being retried
  automatically.
- A not-loaded target remains pending. Codex v2 subagents require their native
  parent handle and cannot be wake targets.
- A wake is input to the target, not a result returned to the sender. Retrieve
  results through a native handle, thread history, or a shared artifact.

Keep queued input concise when existing context remains authoritative. Longer
input is valid when it is deliberately the complete instruction and remains
safe if delayed or duplicated. Use a natural source label when the target could
mistake it for direct human input; the label adds context, not authority.

## Condition Boundaries

Command predicates may run many times with discarded output. Keep them cheap,
side-effect free, and level-triggered: success should remain true until the wake
is handled. When detection needs state, backoff, diagnostics, or expensive
work, use a separate watcher and let wakectl test its durable result.

For an unattended wait whose failure would require user recovery, schedule a
separate time wake for the session that owns and can repair it. Record both job
ids and cancel the remaining job after either path is handled.

The default queue is shared by the host user. Inspect identity and ownership
before canceling a job. Use `--json` when another program will parse output.

## References

- Read `references/runtime-semantics.md` for condition matching, goal identity,
  stop cursors, repeats, delivery outcomes, leases, and SQLite state.
- Read `references/coordination-practices.md` when choosing native polling,
  synchronous waiting, scheduled input, custom watchers, recovery deadlines,
  active steering, or result channels.
- Read `references/troubleshooting.md` when a job remains pending, fails, or
  becomes uncertain.
- Read `references/coordination-principles.md` when composing wakes with native
  controls, goals, thread inspection, streams, or coverage.
- Read `references/worker-workflows.md` for self-management, worker supervision,
  and reviewer chains.
- Read `references/peer-workflows.md` for deferred handoff and peer attention.
- Read `references/host-automation.md` for queue runners, host predicates,
  capacity gates, and external managers.
