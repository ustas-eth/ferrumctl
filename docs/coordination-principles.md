# Coordination Principles

This reference explains how ferrumctl commands compose with each other and with
native Codex controls.

The commands do not form one scheduler or state machine. Each exposes a narrow
surface that can be used alone or combined by a shell script, agent, or host
process.

## Surfaces

`codex-goalctl` reads and edits persisted goal state. It provides durable intent
and counters, but does not start a turn or deliver input.

`codex-wakectl` sends normal input through a selected app-server and can persist
conditions that deliver input later. Its SQLite queue is shared state separate
from Codex.

`codex-threadctl` observes thread status, materialized turns, goal state, and
context records. It also exposes deliberate interruption and compaction. Its
inspection is a read-only aggregate, not an atomic snapshot.

`codex-readcov` reads rollout transcripts and reports recorded file-read
actions. It provides transcript evidence, not verified operating-system access.

## Thread Identity

The common handle is a Codex thread id. For v1 Codex subagents, the spawn
result's `agent_id` is the thread id.

`CODEX_THREAD_ID` identifies the current thread when Codex provides it. It does
not prove that the thread is loaded on a particular app-server.

## Native And Host Control

Use native subagent input when the current session owns the live handle and
needs to send an immediate message. Use native result retrieval for that
subagent's completed response.

Native wait or poll is appropriate when the current turn should stay active and
blocking is acceptable. A queued wake is more suitable when the coordinator
should end its turn and resume after a later condition.

Use ferrumctl when the useful handle is a thread id, when a host process is
coordinating, or when durable goal, queue, history, context, or transcript state
must be accessed outside the target thread.

## Goal And Turn State

App-server status and goal status answer different questions. `idle` means no
turn is running at that moment. It does not mean the thread lacks an active goal
or is free for unrelated work.

An idle thread with an active externally written goal may not have observed the
assignment. A short input asking it to call `get_goal` can start or resume the
work.

Goal completion and turn completion are separate boundaries. A coordinator may
observe a terminal goal before the final response is committed. Use the turn
boundary when the response itself matters.

## Commands And Skills

The command is the host executable. The skill is agent-facing guidance for when
and how to use it.

Humans and scripts can call installed commands directly. Codex agents should
normally use command surfaces whose skills are available in the current
context, unless the user explicitly requests another installed command.

Common subsets:

- `goalctl`: external goal assignment and status checks.
- `wakectl`: immediate input, later attention, stop watches, and host
  predicates.
- `threadctl`: current activity, conversation retrieval, interruption, and
  compaction.
- `readcov`: read counts, interval deltas, overlap, and gaps.
- `goalctl + wakectl`: durable assignment plus input delivery.
- `wakectl + threadctl`: later attention plus deliberate observation.
- `threadctl + readcov`: behavioral inspection plus recorded read evidence.

Missing skills remove guidance for that surface; they do not change the
semantics of the remaining commands.

## Divergence

The surfaces can differ temporarily:

- a goal can change while no turn is running
- two app-servers can share persisted state while only one owns a loaded thread
- a wake can arrive after its condition was handled manually
- materialized turn history can change after rollback or compaction
- a rollout can grow while threadctl or readcov scans it

Treat cross-surface workflows as retryable. Keep durable intent in goals, use
small idempotent queued messages when context remains authoritative, inspect
before destructive control, take read snapshots around the interval of
interest, and cancel only queued jobs owned by the current workflow.
