---
name: codex-wakectl
description: "Use when this or another Codex thread must regain attention after a later time, goal state, turn completion, or host condition, when ordinary input must be scheduled deliberately, or when durable wake jobs and runners must be managed. Synchronous waits are only for scripts or thread-id-only controllers that need an exit status. Do not replace native polling of a live handle or use this for immediate control."
---

# Codex Wakectl

## Purpose

Use `codex-wakectl add` to persist a condition and wake action. A normal wake
adds a short scheduled event to agent context and starts an empty turn when the
target is idle. It restores attention without adding a user message or
replacing the target's existing context, goal, or instructions.

`wait` is a separate synchronous interface. It blocks only its invoking
process, creates no job, and does not notify or wake a thread.

Wakectl does not inspect history for the caller, edit goals, interrupt turns,
or spawn agents.

## Choose A Primitive

Choose according to what should happen to the caller:

- Use native wait or poll when this turn owns a live subagent or terminal handle
  and should remain active.
- Use `wait goal` or `wait stop` when a script or thread-id-only controller
  needs a synchronous exit status.
- Use `add` when this turn should end and a runner should restore attention
  after a later condition.
- Use native subagent input for an immediate message. When only a thread id is
  available, use an immediate control tool only if its skill is available.

The target normally must be loaded on the job's app-server endpoint. A default
shared setup is:

```sh
codex app-server --listen unix://
codex --remote unix://
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

## Schedule A Wake

Schedule by time, goal state or usage, turn completion, or a host predicate:

```sh
codex-wakectl add time --after 30m --to "$SELF"

codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to COORDINATOR

codex-wakectl add goal WORKER --tokens-used-every 2000000 \
  --max-fires 4 --to COORDINATOR

codex-wakectl add stop WORKER --turn TURN_ID --to COORDINATOR

codex-wakectl add cmd --to "$SELF" -- test -f done.txt
```

An unqualified stop watch records a boundary at creation and observes a later
terminal turn. Use `--turn TURN_ID` when one exact turn is the subject,
especially when watch creation can race completion. A goal watch binds to one
assignment; replacing that goal supersedes the watch.

Canonical task names such as `/root/reviewer` can be condition subjects.
`CODEX_THREAD_ID` supplies their tree scope; otherwise pass `--tree THREAD_ID`.
Wakectl resolves each name once and stores the thread id. A parent-owned child
cannot be a delivery target, so direct the wake to `/root` or another thread
that accepts app-server input.

Goal completion and turn completion are separate. Observe the turn boundary
when the final response matters.

## Choose The Action

The default event is generated from the condition and contains a stable job and
fire number. Existing context remains authoritative.

- Omit action options for an event that waits for idle, adds agent context, and
  starts an empty turn.
- Add `--notify-active` when the event should enter current work instead of
  waiting for a separate turn.
- Add `--resume` when wakectl should load an unloaded target. Resume can
  immediately continue an active goal.
- Add `--input MESSAGE` only when delayed ordinary input is deliberately the
  instruction. It waits for idle and must remain valid if late or duplicated.

```sh
codex-wakectl add cmd --to WORKER \
  --input "Continue from done.txt and complete the next step." -- \
  test -f done.txt
```

Use immediate thread steering for a correction to active work. Do not schedule
such intervention speculatively.

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

- A scheduled event is an agent message, not a system instruction or user
  message. It remains in history and can be compacted with other context.
- Event injection and empty turn start are separate requests. Treat the
  recorded delivery mode as authoritative when activity wins that race.
- Delivery is at-least-once. An event or input may be late or duplicated; an
  ambiguous outcome becomes `uncertain` instead of being retried automatically.
- A not-loaded target remains pending unless the event uses `--resume`.
- A parent-owned child can be watched, but its native parent controls lifecycle;
  direct the wake to `/root` or another thread that accepts direct control.
- A wake does not return the target's result. Retrieve results through a native
  handle, thread history, or a shared artifact.

Label explicit `--input` naturally when the target could mistake it for direct
human input. A label adds context, not authority.

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
  synchronous waiting, event wakes, explicit input, resume, custom watchers,
  recovery deadlines, or result channels.
- Read `references/troubleshooting.md` when a job remains pending, fails, or
  becomes uncertain.
- Read `references/coordination-principles.md` when composing wakes with native
  controls, goals, thread inspection, streams, or coverage.
- Read `references/worker-workflows.md` for self-management, worker supervision,
  and reviewer chains.
- Read `references/peer-workflows.md` for deferred handoff and peer attention.
- Read `references/host-automation.md` for queue runners, host predicates,
  capacity gates, and external managers.
