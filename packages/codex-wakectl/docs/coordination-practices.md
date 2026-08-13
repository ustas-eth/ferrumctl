# Coordination Practices

This reference describes how immediate control, synchronous waits, and queued
wakes fit into Codex workflows.

## Identity And Endpoint

Codex exposes the current thread id to shell commands through
`CODEX_THREAD_ID`:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

Wakeability is scoped to one app-server endpoint. A thread loaded through one
endpoint cannot receive input through another. Use the same `--endpoint` for
the sessions and queued jobs in one workflow.

## Choosing A Channel

Use native subagent input when the current session owns the live handle and
needs to send an immediate message. Use native wait or poll when the current
turn owns the live subagent or terminal handle and should stay active.

`codex-threadctl start` and `steer` provide immediate thread-id control when no
native handle is available.

Use `codex-wakectl wait` when a script or thread-id-only controller needs an
exit status from a Codex condition. It polls in the invoking process, exits `0`
when ready and nonzero on timeout, sends no input, and persists no job. If a
shell tool moves that process to the background, its caller must still observe
the process finishing; completion does not start a Codex turn.

Use a queued wake when the current process or Codex turn should end while a
runner watches the condition and restores attention later. The default action
adds a short scheduled event to agent context and starts an empty turn when the
target is idle. Use `--input MESSAGE` only when delayed ordinary input is the
intended operation.

Inspect unclear thread state before choosing whether to wait or schedule a
wake. A wake changes the target's attention; it does not return the target's
result to the sender. Native subagent results, materialized thread history, and
shared artifacts are separate result channels.

## Long Host Waits

The practices in this section concern queued `add cmd` jobs. A synchronous
`wait cmd` only moves the predicate loop into another process.

An `add cmd` command is evaluated from scratch on every runner pass. It is best
suited to a level-triggered probe: a cheap, side-effect-free check that returns
`0` for as long as the resulting wake remains useful. A file-exists check is a
typical predicate. A planning run, state transition, or polling loop is not.

When detection needs state, backoff, diagnostics, or expensive work, use a
separate watcher. The watcher can persist a ready result atomically, while the
wakectl job tests only that durable state. Keeping detection separate from
delivery makes the predicate easy to rerun and leaves wakectl responsible for
idle handling and delivery records.

A custom watcher needs an explicit host lifecycle that outlives the initiating
Codex turn. Its process or service identity should be retained for inspection
and cleanup, and diagnostics should be written somewhere the resumed session
can read.

The watcher can instead deliver directly with `codex-threadctl wake` or `start`
once the target is idle; an equivalent app-server client is the lower-level
alternative.
This avoids the second polling step, but the watcher then owns target
availability, retries, uncertain outcomes, and duplicate suppression as well as
its process lifecycle. Use this form when those controls already belong in the
custom process, not merely because the readiness check needs more than one shell
command.

Long unattended waits benefit from a separate time wake at a reasonable review
deadline. Both paths should normally wake the session that owns and can repair
the wait. If the primary condition has not fired, that session can inspect the
job, validate the watcher and predicate, and repair or re-arm them. Record both
job ids and cancel the pending counterpart after either path is handled.

A deadline in the same wakectl queue protects against predicate and watcher
mistakes, not against a stopped runner. Workflows that must recover from runner
failure need an independent host supervisor. That additional failure domain is
usually unnecessary when occasional user recovery is acceptable.

## Goal State And Idleness

App-server `idle` means no turn is running. It does not mean the target lacks an
active goal or is free for unrelated work.

An idle worker with an active externally assigned goal may not have observed
that goal. An event wake starts a turn without adding another instruction; the
goal remains the authority. Use app-server status to choose a delivery policy,
not to infer work ownership.

A terminal goal status and a completed turn are separate boundaries. If a
coordinator needs the worker's final response, wait for the current turn to stop
or inspect it after the goal predicate fires.

## Turn Completion

An unqualified stop watch observes a terminal turn after the boundary recorded
at creation. Arm it before starting the turn. If creation can race a known
turn's completion, bind the watch with `--turn TURN_ID`; the exact turn still
matches when it is already terminal. Use `--turn latest` only when the newest
existing turn is deliberately the target.

## Steering And Checkpoints

By default, an event waits for an idle target. `--notify-active` instead injects
the event into current work and finishes the job without starting another turn.
It is appropriate only when prompt awareness is useful and the event does not
need a separate response. Use immediate `codex-threadctl steer` with an exact
turn id for a correction or constraint.

A running worker can send a handoff before its own final response is committed.
Treat the handoff as readiness; use a stop condition when the receiver depends
on the committed turn boundary.

For a blocking checkpoint, first prevent automatic continuation by pausing any
active goal. Interrupt the exact active turn and wait for terminal completion.
If a later wake should follow the checkpoint response, arm its stop watch before
starting the checkpoint turn, or bind it to the checkpoint turn id.

## Persisted Jobs And Actions

Queued jobs persist their action, predicates, endpoints, and thread ids in the
SQLite database. An explicit input action also persists its message. Avoid
secrets, large private context, and fragile one-time instructions in that state.

The default action generates a short `Scheduled event JOB/FIRE` agent message
from the matched condition, then starts an empty turn if the target is idle.
The event remains in history but is not ordinary user input and carries no new
instructional authority.

`--input MESSAGE` retains the ordinary confirmed input path and waits for an
idle target. The text does not identify its logical sender, so label it
naturally when it could be mistaken for direct human input. It must remain safe
if delayed or duplicated.

`--resume` applies only to event wakes. It loads an otherwise unloaded target;
if that thread has an active goal, Codex can continue the goal immediately.
The event is then injected into that active turn. Resume does not coordinate a
copy of the same thread loaded on another app-server.

Record job ids when a workflow will need cleanup. The default queue is shared;
proximity in `codex-wakectl list` does not establish ownership.
