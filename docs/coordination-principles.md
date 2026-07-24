# Coordination Principles

This reference explains how ferrumctl commands compose with each other and with
native Codex controls.

The commands do not form one scheduler or state machine. Each exposes a narrow
surface that can be used alone or combined by a shell script, agent, or host
process.

## Surfaces

`codex-goalctl` reads and edits persisted goal state. It provides durable intent
and counters, but does not start a turn or deliver input.

`codex-limitctl` reads account-wide subscription limits and daily token
activity, tests remaining-capacity predicates, and reconstructs local rollout
history. Local activity is comparative evidence, not exact account
attribution. It does not measure thread context or goal token usage.

`codex-streamctl` persists ordered immutable entries and cumulative per-reader
acknowledgements. It provides durable shared exchange state, but no
notification, wake, membership, or authorization.

`codex-wakectl` persists jobs that deliver normal input after later conditions.
It also offers synchronous condition polling for scripts; those waits do not
use the queue or deliver input.

`codex-threadctl` discovers and searches persisted threads and observes thread
status, materialized item ranges, goal state, context records, and running
terminal processes. It also injects advisory agent notices, wakes loaded idle
threads without user input, starts or steers immediate input, resumes persisted
threads, interrupts exact turns, and terminates exact terminal processes. Its
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

Native wait or poll is appropriate when the current turn owns the live
subagent or terminal handle and should stay active. A synchronous
`codex-wakectl wait` is useful when a script or thread-id-only controller needs
an exit status from a Codex condition. A queued wake is more suitable when the
coordinator should end its turn and resume after a later condition.

Use ferrumctl when the useful handle is a thread id, when a host process is
coordinating, or when durable goal, stream, queue, history, context, or
transcript state must be accessed outside the target thread.

Normal cross-thread input can look like direct human input. When the distinction
matters, begin with a natural label such as `From coordinator:`, `From
reviewer:`, `Self-scheduled reminder:`, or `Automated event:`. Name the
transport only when delivery mechanics matter, for example `From coordinator
via threadctl:`. `codex-threadctl start`, `codex-threadctl steer`, and
`codex-wakectl` preserve the supplied text; they do not add labels. A label
clarifies origin but does not prove identity or override existing instructions.
`codex-threadctl notify` instead injects an advisory agent message with a
caller-supplied author, which is provenance rather than authentication.

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

- `codex-goalctl`: external goal assignment and status checks.
- `codex-limitctl`: subscription capacity, usage trends, local thread activity,
  and shell predicates.
- `codex-streamctl`: durable peer records and processed-through cursors.
- `codex-wakectl`: later attention, stop watches, host predicates, and synchronous
  Codex conditions for scripts.
- `codex-threadctl`: current and ordered activity, conversation retrieval,
  immediate input, resume, and turn-scoped interruption.
- `codex-readcov`: read counts, interval deltas, overlap, and gaps.
- `codex-goalctl + codex-threadctl`: durable assignment plus immediate input.
- `codex-goalctl + codex-wakectl`: durable assignment plus later delivery.
- `codex-streamctl + codex-threadctl`: durable peer exchange plus advisory
  notice and optional idle execution.
- `codex-limitctl + codex-wakectl`: capacity observation plus later attention.
- `codex-wakectl + codex-threadctl`: later attention plus observation.
- `codex-threadctl + codex-readcov`: thread state plus recorded read evidence.

Missing skills remove guidance for that surface; they do not change the
semantics of the remaining commands.

## Divergence

The surfaces can differ temporarily:

- a goal can change while no turn is running
- two app-servers can share persisted state while only one owns a loaded thread
- a wake can arrive after its condition was handled manually
- a stream entry can commit while its advisory notice is lost or duplicated
- materialized turn history can change after rollback or compaction
- a rollout can grow while `codex-threadctl` or `codex-readcov` scans it
- account capacity can change immediately after `codex-limitctl` reads it

Treat cross-surface workflows as retryable. Keep durable intent in goals, use
small idempotent queued messages when context remains authoritative, inspect
before interruption, take read snapshots around the interval of
interest, and cancel only queued jobs owned by the current workflow.
