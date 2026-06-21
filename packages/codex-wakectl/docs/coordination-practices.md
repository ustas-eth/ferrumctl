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

Use `send --allow-active` for non-blocking steering: a small correction,
reminder, or new constraint that the target can apply without stopping.

Sending to an idle goal-backed worker is fine when the message is meant to make
it observe or continue the current goal. Do not treat idle as permission to
assign unrelated work.

Use a checkpoint when the answer must be inspected before work continues. Pause
or otherwise stop the target first, ask the checkpoint question, inspect the
result, then resume. For goal-backed workers, that usually means a goal status
update plus a wake message to continue from `get_goal`.

If the coordinator will not wait synchronously, arm a `stop` wake before sending
the checkpoint question so the coordinator is woken when the answer turn ends.

## Scripting

`wait` is a Unix condition primitive. It is useful in shell scripts, CI jobs, or
host processes that need an exit code for a Codex-specific condition.

Use `--json` when another program will parse `codex-wakectl` output. Text output
is for humans and concise shell inspection.

## Persisted Job Contents

Queued jobs persist message text, predicates, endpoints, and thread ids in the
SQLite state database. Avoid storing secrets, large private context, or fragile
one-time instructions in wake messages or command predicates.

If a workflow may need cleanup, record the job ids it creates in its own notes
or artifacts. Do not infer ownership from proximity in `codex-wakectl list`
output.

## Wake Messages

Wake messages should be idempotent because queued delivery is at-least-once.
Good messages state why the wake fired, what to inspect, and what next action is
expected.

For peer handoffs or delegated supervision, the message should make ownership
clear: what the receiving thread owns, whether it should report upward, and
whether any remaining jobs should be canceled.
