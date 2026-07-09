<!-- Generated from packages/codex-wakectl/docs/coordination-practices.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coordination Practices

This reference describes how `codex-wakectl` fits into host scripts, Codex
threads, and multi-thread supervision. It focuses on choosing the right
coordination primitive.

## Current Thread Identity

Codex exposes the current thread id to shell commands through
`CODEX_THREAD_ID`:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

That value is only an identity. It does not mean the thread is wakeable through
`codex-wakectl`. Wakeability also requires the thread to be loaded on the same
app-server endpoint used by wakectl.

## App-Server Endpoint

Wakeability is scoped to one app-server endpoint. A thread started through one
endpoint cannot be woken through another.

```sh
codex app-server --listen unix://
codex --remote unix://
codex-wakectl loaded
```

The default `unix://` endpoint resolves under `CODEX_HOME`. If you choose a
custom socket path, use the same `--endpoint` on every `codex-wakectl` command
and queued job that should target that server.

## Inspect Before Control

Use `inspect` when another thread's current state is not already clear:

```sh
codex-wakectl inspect THREAD_ID
```

The report distinguishes thread status, goal status, the newest turn, recent
structured activity, and the previous turn's agent response. It does not return
command output or modify the thread.

## Native Handles, Wait, and Queued Wakes

When a supervising agent has a native subagent input handle, that handle is the
best immediate way to send a direct message to the subagent.

Native wait or poll is useful when the supervisor should stay active and
blocking for the worker is acceptable. It is less useful for long-running goal
work where the supervisor should end its turn and be resumed later.

`codex-wakectl wait` is useful when the coordinator has only a thread id plus
app-server access. It blocks the invoking process until a Codex condition is
ready, exits `0` when ready, and exits nonzero on timeout. It does not persist a
job and does not send any input turn.

Queued wakes are for durable later attention. A queued job lets the current
process or Codex turn end while another runner keeps checking the condition and
sends a future input turn.

After a wake, retrieve a native subagent's completed response through the native
handle. For a standalone thread, use `inspect` for its recent response and
activity, or read a shared result artifact when the workflow defines one.

## Goal State And Idleness

App-server `idle` only means no turn is running. It does not mean the target has
no active assignment, and it does not mean the target has observed a recently
written goal.

A goal-backed worker with app-server `idle` and goal status `active` has
durable work assigned, but no turn is currently acting on it. A small wake that
tells it to call `get_goal` often starts or resumes that work. Use app-server
status only to decide whether delivery needs `--allow-active`.

## Steering And Checkpoints

`codex-wakectl send` starts a normal turn in the target thread. It is not a
reply channel to the sender. If the target has an active goal, it may answer in
its own transcript and continue working.

A running worker must send a handoff message before its own turn ends, so the
receiver may wake before the worker's final response is committed. Treat that
message as a readiness signal. If the worker is still active, wait for its turn
to stop before depending on the final response; if it is idle, the boundary has
already been committed.

A terminal goal status is also separate from the current turn boundary. When a
goal watch wakes a coordinator, inspect the worker or wait for its current turn
to stop before depending on its final response.

Use `send --allow-active` for non-blocking steering: a small correction,
reminder, or new constraint that the target can apply without stopping.

Sending to an idle goal-backed worker is fine when the message is meant to make
it observe or continue the current goal. Do not treat idle as permission to
assign unrelated work.

Use a checkpoint when the answer must be inspected before work continues. For a
goal-backed worker, pause the goal first so it will not continue automatically,
then interrupt the active turn. Changing goal status alone does not interrupt a
turn already in progress.

After the worker is stopped, arm a stop watch before sending the checkpoint
question. Inspect the answer when the watch wakes the coordinator, then resume
the goal and send a short continuation message.

If the coordinator will wait synchronously, `wait stop` provides the same
durable turn-completion condition without sending a wake.

## Scripting

`wait` is a Unix condition primitive. It is useful in shell scripts, CI jobs, or
host processes that need an exit code for a Codex-specific condition.

Use `--json` when another program will parse `codex-wakectl` output. Text output
is for humans and concise shell inspection.

## Persisted Job Contents

Queued jobs persist message text, predicates, endpoints, and thread ids in the
SQLite state database. Avoid storing secrets, large private context, or fragile
one-time instructions in wake messages or command predicates.

Command predicates store argv and cwd, but execute in the runner's environment.
Use explicit paths and inputs when a predicate must also work under systemd.

If a workflow may need cleanup, record the job ids it creates in its own notes
or artifacts. Do not infer ownership from proximity in `codex-wakectl list`
output.

## Wake Messages

Wake messages become ordinary user messages in the target transcript. They
continue the existing session, consume context, and may survive into compaction
summaries.

Immediate `send` input can be the instruction you intend to deliver. Queued
wake input is different because it may fire late, retry after a failure, or be
read after surrounding state changed.

For queued wakes, prefer short messages that identify the event and next
decision. Use longer queued input only when it is deliberately the instruction
and remains safe if delivered late or more than once. Avoid storing evolving
approval history, command runbooks, full plans, or project state in queued wake
text.

For peer handoffs or delegated supervision, a short ownership marker can help
when the receiver already has context. If it does not, send or assign the
needed instructions deliberately.
