<!-- Generated from docs/coordination-principles.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coordination Principles

Ferrumctl commands expose independent state and control surfaces. They can be
installed separately and do not form one scheduler or state machine.

In an agent session, a command should normally be used only when its skill is
available or the user explicitly requests that command. Missing packages remove
workflow layers; they do not change the semantics of the remaining tools.

## State Surfaces

| Surface | Authority | Does not establish |
| --- | --- | --- |
| Goal state | Durable objective, status, budget, and counters | Turn execution or message delivery |
| Thread state | Live app-server status and materialized history | An atomic or immutable transcript |
| Wake queue | Conditions and later input delivery | The target's result |
| Stream state | Ordered entries and reader acknowledgements | Notification, membership, or authorization |
| Limit state | Current account observations and local usage history | Reserved capacity or exact thread attribution |
| Read coverage | Transcript-recorded file-read actions | Verified file access or complete model context |

The surfaces can differ in freshness. Output and documentation should preserve
which source produced an observation rather than presenting a synthetic state
as authoritative.

## Identity And Reachability

The common handle is a Codex thread id. For v1 subagents, the spawn result's
`agent_id` is that thread id. `CODEX_THREAD_ID` identifies the current thread
when Codex provides it.

A thread id identifies persisted state under a Codex home. It does not identify
which app-server, if any, owns live execution. Immediate and scheduled input
must use the endpoint on which the target is loaded.

SQLite state is shared by callers using the same host user and state path.
Thread ids, stream authors, readers, and message labels provide provenance and
scope; they are not authentication.

## Choosing Control

Use a native subagent handle for immediate input, waiting, and result retrieval
when the current session owns that handle.

Use thread control when a thread id is the useful handle, persisted history is
needed, or an immediate app-server operation is intentional. Use a queued wake
when attention must survive the current turn or wait for a later condition.

Keep durable assignment in goal state. Keep durable peer content in a stream.
Use input or advisory notification to draw attention to that state rather than
copying it into several conversations.

Use account limits to gate work only when a policy supplies the threshold. Use
read coverage as evidence about a defined transcript interval, not as a proxy
for task correctness.

## Independent Boundaries

- Goal completion and turn completion are separate. Observe the turn when the
  final response matters.
- App-server `idle` means no turn is running. It does not remove an active goal
  or grant another participant ownership of the thread.
- A stream append, its notification, a later wake, and reader acknowledgement
  are separate operations.
- A matched wake condition, delivered input, target action, and result
  retrieval are separate events.
- Account capacity, goal token usage, and context-window usage are different
  measurements.
- Materialized history and rollout evidence can change or grow independently.

## Composition

Ferrumctl provides no transaction across packages. Establish durable state
before announcing it: assign a goal before prompting work, append a stream entry
before notifying its position, and take a read snapshot before the interval of
interest.

Treat uncertain delivery and ambiguous writes as reconciliation cases rather
than automatic retry signals. Use exact identifiers from current observations,
prefer idempotent event messages, and cancel only shared-state jobs owned by the
current workflow.
