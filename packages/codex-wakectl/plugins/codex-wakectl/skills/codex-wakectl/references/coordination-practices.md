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
needs to send an immediate message. Use native wait or poll when this turn
should stay active and blocking for the worker is acceptable.

`codex-threadctl start` and `steer` provide immediate thread-id control when no
native handle is available.

Use `codex-wakectl wait` when a script or session should block on a Codex
condition without sending input. It exits `0` when ready and nonzero on timeout;
it does not persist a job.

Use a queued wake when the current process or Codex turn should end while a
runner watches the condition and resumes attention later.

Inspect unclear thread state before choosing whether to wait or schedule input.
A wake is input to its target, not a result returned to its sender. Native
subagent results, materialized thread history, and shared artifacts are separate
result channels.

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

Queued messages may arrive late or more than once. Prefer a short event marker
when existing thread context remains authoritative. Longer queued input is
valid when it is deliberately the complete instruction and remains safe under
delayed or duplicate delivery.

Record job ids when a workflow will need cleanup. The default queue is shared;
proximity in `codex-wakectl list` does not establish ownership.
