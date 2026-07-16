<!-- Generated from packages/codex-wakectl/docs/coordination-practices.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coordination Practices

This reference describes how immediate input, synchronous waits, and queued
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
runner watches the condition and resumes attention later.

Inspect unclear thread state before choosing whether to wait or schedule input.
A wake is input to its target, not a result returned to its sender. Native
subagent results, materialized thread history, and shared artifacts are separate
result channels.

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

The watcher can instead deliver directly with `codex-threadctl start` once the
target is idle; an equivalent app-server client is the lower-level alternative.
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
that goal. A short input asking it to call `get_goal` can start or resume the
assignment. Use app-server status to choose a delivery policy, not to infer work
ownership.

A terminal goal status and a completed turn are separate boundaries. If a
coordinator needs the worker's final response, wait for the current turn to stop
or inspect it after the goal predicate fires.

## Steering And Checkpoints

For queued delivery, `--allow-active` permits native expected-turn steering for
a correction, reminder, or constraint that remains valid during current work.
Ordinary follow-up should wait for an idle target.

A running worker can send a handoff before its own final response is committed.
Treat the handoff as readiness; use a stop condition when the receiver depends
on the committed turn boundary.

For a blocking checkpoint, first prevent automatic continuation by pausing any
active goal. Interrupt the exact active turn and wait for terminal completion.
If a later wake should follow the checkpoint response, arm its stop watch before
starting the checkpoint turn.

## Persisted Jobs And Messages

Queued jobs persist message text, predicates, endpoints, and thread ids in the
SQLite database. Avoid secrets, large private context, and fragile one-time
instructions in that state.

Queued input does not identify its logical sender. When its source could be
confused with direct human input, use a natural label such as `From
coordinator:`, `Self-scheduled reminder:`, or `Automated event:`. Mention
wakectl only when the transport itself matters. A label provides context, not
proof of identity or permission to override existing instructions.

Queued messages may arrive late or more than once. Prefer a short event marker
when existing thread context remains authoritative. Longer queued input is
valid when it is deliberately the complete instruction and remains safe under
delayed or duplicate delivery.

Record job ids when a workflow will need cleanup. The default queue is shared;
proximity in `codex-wakectl list` does not establish ownership.
