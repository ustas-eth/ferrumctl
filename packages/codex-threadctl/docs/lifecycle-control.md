# Immediate Thread Control

This reference describes the native operations behind thread start, steering,
resume, and interruption.

## Endpoint Ownership

Immediate control requires the target to be loaded on the selected app-server.
A thread id identifies persisted state under a Codex home, but it does not
identify which server currently owns live execution.

`resume` loads persisted state on the selected server without starting a turn.
It does not detect or coordinate another app-server that may have loaded the
same thread.

Codex rejects direct app-server input to v2 subagents. Control those subagents
through their native parent handle; threadctl start and steer apply to threads
that accept direct input.

## Starting Input

`start` observes a loaded thread as idle, submits `turn/start` with a unique
client message id, and waits until that message appears in materialized turn
history. The result reports the actual turn id and whether Codex started a new
turn or steered the message into a turn that won the race.

The idle observation and `turn/start` request are not atomic. Confirmation
makes the outcome visible but cannot undo input that raced into active work. If
confirmation fails, the operation is uncertain: retrying can duplicate the
message.

## Steering

`steer` uses native `turn/steer` with a required expected turn id. Codex rejects
the request if that turn is no longer the active regular turn. Review and manual
compaction turns do not accept steering.

A rejected JSON-RPC request is a definite failure. A connection or protocol
failure after start or steer was submitted has an uncertain outcome and should
be reconciled by client message id before retrying. Structured `inspect` and
`messages` output preserves that id when Codex materializes the message.

Threadctl does not answer approval or user-input requests raised later by the
turn. A capable app-server client must remain available to resolve them.

## Interruption

`interrupt` sends `turn/interrupt` for an explicit thread and turn id. Native
turn-id validation prevents a stale request from interrupting a replacement
turn.

The immediate result is an interruption request, not terminal completion. With
`--wait`, threadctl follows that exact turn until materialized history reports a
terminal status. Interruption does not pause a goal or terminate background
terminals.
