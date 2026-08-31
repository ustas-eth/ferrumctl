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
| Wake queue | Conditions and later event or input delivery | The target's result |
| Stream state | Ordered entries and reader acknowledgements | Notification, membership, or authorization |
| Limit state | Current account observations and local usage history | Reserved capacity or exact thread attribution |
| Read coverage | Transcript-recorded file-read actions | Verified file access or complete model context |
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
Persisted goals, snapshots, and jobs remain bound to thread ids. A canonical
task name does not transfer lifecycle ownership from the native parent.

A thread id identifies persisted state under a Codex home. It does not identify
which app-server, if any, owns live execution. Immediate control and scheduled
wakes must use the endpoint on which the target is loaded, unless an explicit
resume policy loads it there.

SQLite state is shared by callers using the same host user and state path.
Thread ids, stream authors, readers, and message labels provide provenance and
scope; they are not authentication.

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

Keep durable assignment in goal state. Keep durable peer content in a stream.
When a stream is authoritative, use native input or advisory notification only
to draw attention to its committed position rather than copying its content into
several conversations. Notification does not start an idle recipient; lifecycle
control remains with the native owner or a target that accepts direct input.

Use account limits to gate work only when a policy supplies the threshold. Use
read coverage as evidence about a defined transcript interval, not as a proxy
for task correctness.

Use memory transfer only when opaque compaction state is itself the needed
input. An in-place injection is durable; use a disposable thread when the
original conversation must remain unchanged.

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
