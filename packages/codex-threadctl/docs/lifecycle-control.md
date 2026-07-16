# Immediate Thread Control

This reference describes the native operations behind thread start, steering,
resume, interruption, and terminal-process control.

## Endpoint Ownership

Starting, steering, interruption, and terminal-process control require the
target to be loaded on the selected app-server. A thread id identifies
persisted state under a Codex home, but it does not identify which server
currently owns live execution.

## Resuming

`resume` loads persisted state on the selected server without adding a user
message. Codex emits the thread's goal snapshot after the resume response and
can immediately continue an active goal when the resumed thread is idle.

App-server does not provide an atomic "resume only if no goal is active"
operation. Threadctl therefore requires `--continue-goal` for every resume. The
flag acknowledges possible continuation; it does not activate or change the
goal. Resume also does not detect or coordinate another app-server that may
have loaded the same thread.

Codex rejects direct app-server input to v2 subagents. Control those subagents
through their native parent handle; threadctl start and steer apply to threads
that accept direct input.

## Starting Input

`start` observes a loaded thread as idle, submits `turn/start` with a unique
client message id, and waits until that message appears in materialized turn
history. The result reports the actual turn id and whether Codex started a new
turn or steered the message into a turn that won the race.

The client message id confirms delivery; it does not identify the logical
sender. When provenance matters, include it in the text with a natural label
such as `From coordinator:`. The label provides context, not proof of identity.

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

## Terminal Processes

`terminals` lists processes that Codex still tracks for one loaded thread. Each
record includes the native process id used by app-server, its originating item,
command, and working directory, with OS resource fields when available.

Codex can reuse process ids after a terminal exits. `terminate-terminal`
therefore requires both the process id and originating item id from a current
`terminals` listing. Threadctl re-lists the thread and rejects a missing process
or changed item before sending the native termination request.

The identity check and native request are not atomic because app-server accepts
only the process id. Use a fresh listing and act promptly. Success means
app-server confirmed termination; failure does not by itself prove the process
was absent. Termination does not interrupt the model turn or change goal state.
When a thread inspects itself, the inspection command can appear in the result
while it is still running.
