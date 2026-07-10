<!-- Generated from packages/codex-threadctl/docs/lifecycle-control.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Lifecycle Control

This reference describes the safeguards and remaining races around `interrupt`
and `compact`.

## Endpoint Ownership

Both commands require the target thread to be loaded on the selected app-server.
A thread id identifies persisted state globally under the same Codex home, but
live control belongs to the server process that loaded the thread.

## Interruption

`interrupt` first observes the thread as active, then obtains the current
in-progress turn id and submits `turn/interrupt` with that id. If the turn
changes before Codex accepts the request, Codex rejects the stale id instead of
interrupting a different turn.

Interruption stops the live turn. It does not pause or clear a persisted goal,
so a separate input or goal-driven continuation can start work again.

## Compaction

Native `thread/compact/start` starts a standalone compaction turn. Codex creates
that task by replacing any task already running, so threadctl refuses compaction
unless it observes the thread as loaded and idle. It also refuses an active
goal; pause the goal first when compaction must remain a maintenance operation.

Those checks and the native request are not atomic. Another controller can send
input between them, and Codex exposes no idle precondition on the compaction
method. Avoid manual compaction while another controller may concurrently start
work.

The command reports when compaction has started. A later `inspect` shows the
new context observation and compaction record after Codex persists them.
