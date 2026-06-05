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

## Native Handles, Wait, and Queued Wakes

When a supervising agent has a native subagent handle and a native wait/poll
operation, that native channel is the best way to wait for the subagent. It has
more context than wakectl: the agent object, completion state, and response
channel.

`codex-wakectl wait` is useful when the coordinator has only a thread id plus
app-server access. It blocks the invoking process until a Codex condition is
ready, exits `0` when ready, and exits nonzero on timeout. It does not persist a
job and does not send any input turn.

Queued wakes are for durable later attention. A queued job lets the current
process or Codex turn end while another runner keeps checking the condition and
sends a future input turn.

## Scripting

`wait` is a Unix condition primitive. It is useful in shell scripts, CI jobs, or
host processes that need an exit code for a Codex-specific condition.

Use `--json` when another program will parse `codex-wakectl` output. Text output
is for humans and concise shell inspection.

## Persisted Job Contents

Queued jobs persist message text, predicates, endpoints, and thread ids in the
SQLite state database. Avoid storing secrets, large private context, or fragile
one-time instructions in wake messages or command predicates.

## Wake Messages

Wake messages should be idempotent because queued delivery is at-least-once.
Good messages state why the wake fired, what to inspect, and what next action is
expected.

For peer handoffs or delegated supervision, the message should make ownership
clear: what the receiving thread owns, whether it should report upward, and
whether any remaining jobs should be canceled.
