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
| Goal state | Durable objective, status, budget, and counters | Turn execution, message delivery, or retraction of earlier instructions |
| Thread state | Live app-server status and materialized history | An atomic or immutable transcript |
| Wake queue | Conditions and later event or input delivery | The target's result |
| Stream state | Ordered entries and reader acknowledgements | Notification, membership, or authorization |
| Limit state | Current account observations and local usage history | Reserved capacity or exact thread attribution |
| Compaction memory | Opaque memory items and their rollout sightings | Donor identity, temporary scope, or model interpretation |

The surfaces can differ in freshness. Output and documentation should preserve
which source produced an observation rather than presenting a synthetic state
as authoritative.

## Identity And Reachability

The common handle is a Codex thread id. For v1 subagents, the spawn result's
`agent_id` is that thread id. `CODEX_THREAD_ID` identifies the current thread
when Codex provides it.

`codex-threadctl create` produces a persisted root whose thread id can be
controlled directly through the selected app-server. It is independent of the
creator's native agent tree and has no automatic parent result channel.

Some native subagent tools expose a canonical task name such as
`/root/reviewer`. It is a tree-local routing handle, not the persisted identity,
and can be reused after an agent closes. When the threadctl skill is available,
an unambiguous canonical task name can be used directly for an immediate
operation or resolved to its thread id. Resolve it when another package requires
a thread id or when the reference must remain attached to that conversation.
Persisted goals and wake jobs remain bound to thread ids. A canonical
task name does not transfer lifecycle ownership from the native parent.

A thread id identifies persisted state under a Codex home. It does not identify
which app-server, if any, owns live execution. Immediate control and scheduled
wakes must use the endpoint on which the target is loaded, unless an explicit
resume policy loads it there.

SQLite state is shared by callers using the same host user and state path.
Thread ids, stream authors, readers, and message labels provide provenance and
scope; they are not authentication.

For selected worker operations without direct access to shared sockets or
stores, see [Restricted Worker Operations](https://github.com/ustas-eth/ferrumctl/blob/main/docs/restricted-operations.md).

## Choosing Control

Use a native subagent handle for direct input, lifecycle control, waiting, and
result retrieval when the current session owns that handle. Current Codex keeps
v2 children under this parent ownership and rejects direct external input,
injected context, and goal changes to those children.

When a host process or another thread must control a worker directly, create an
independent root on the shared app-server from the outset. Task-name resolution
and resume do not transfer ownership.

Use thread control when a thread id is the useful handle, persisted history is
needed, or an immediate app-server operation is intentional. Use a queued wake
when attention must survive the current turn or wait for a later condition. A
normal queued wake adds a short agent event and starts an empty turn; schedule
ordinary input only when its text is deliberately the instruction.

Keep durable assignment in goal state. For direct agent communication, use
native messages or threadctl `send`; `input` deliberately carries the user role.
A coordinator is still an agent. A stream adds shared ordering and reader
acknowledgements when those are needed. Once a stream is authoritative, announce
its committed position rather than copying its contents across conversations.
Agent-message acceptance and execution remain separate; `send --wake` composes
them for a directly controlled recipient.

Use account limits to gate work only when a policy supplies the threshold.

Use memory transfer only when opaque compaction state is itself the needed
input. An in-place injection is durable; use a disposable thread when the
original conversation must remain unchanged.

## Goals And Conversation Framing

Goal state and user input are separate. Assigning or activating a goal does not
replace earlier user messages. The latest user message can keep framing what
the agent is doing, how it should respond, and when it should stop, even after
later goal changes and substantial work.

Compaction can retain that message while compressing the circumstances that
made it appropriate. An empty wake continues the same conversation. Neither
operation establishes which earlier instructions still apply to the current
assignment.

A brief, deliberate anchoring user message can renew the ongoing frame when a
goal is assigned or after situational steering. For example:

> Continue working autonomously toward the active goal, incorporating relevant
> updates from this conversation.

The goal still carries the objective, status, and budget. The message explains
how the conversation relates to that work, preserving continuing constraints
and clarifying those that have changed. Anchoring is useful when the framing
needs renewal, rather than after every goal update or wake.

A human can provide that message directly; threadctl `input` provides the
explicit user-role path for directly controlled threads. Ordinary agent reports
and coordination still use native messages or `send`. When an orchestrator or
host process supplies user input, identify its origin in the text rather than
presenting it as direct human speech.

## Independent Boundaries

- Goal completion and turn completion are separate. Observe the turn when the
  final response matters.
- App-server `idle` means no turn is running. It does not remove an active goal
  or grant another participant ownership of the thread.
- A stream append, its notification, a later wake, and reader acknowledgement
  are separate operations.
- A matched wake condition, delivered event or input, target action, and result
  retrieval are separate events.
- Account capacity, goal token usage, and context-window usage are different
  measurements.
- Materialized history and rollout evidence can change or grow independently.
- Memory injection acceptance, model receipt, and later assimilation are
  separate events.
- Model-visible delivery, semantic use, and retained source awareness are
  separate outcomes. Carry an actor or source label in ordinary content when
  later attribution matters; transport metadata alone is not enough.

## Composition

Ferrumctl provides no transaction across packages. Establish durable state
before announcing it: assign a goal before prompting work, append a stream entry
before notifying its position, and take a read snapshot before the interval of
interest.

Treat uncertain delivery and ambiguous writes as reconciliation cases rather
than automatic retry signals. Use exact identifiers from current observations,
prefer idempotent event messages, and cancel only shared-state jobs owned by the
current workflow.
