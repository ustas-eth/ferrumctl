# Observation Semantics

This reference describes what `codex-threadctl` observes and where that view can
be incomplete or stale.

## Thread Discovery

`list` reads Codex's persisted thread index. Without a relationship filter it
returns non-archived interactive sessions across model providers. `--parent`
selects threads spawned directly by one thread; `--ancestor` includes spawned
descendants at any depth. Relationship results come from Codex's persisted
spawn graph, so closing a native agent handle does not remove them. Review and
Guardian threads do not participate in that graph.

Results default to newest turn recency and can instead be ordered by creation
or update time. The reported `server` value is thread state on the selected
app-server. It is not the native agent manager's lifecycle status, and
`notLoaded` does not distinguish a completed agent from any other stored thread.
Use `inspect` to read retained turn state and responses.

`search` queries persisted thread content and returns the matching thread with
a server-selected snippet. It uses the same non-archived interactive thread
scope as unfiltered discovery. A snippet helps locate a thread; it is not an
exact message locator. Use `messages` and `message` when the retained exchange
itself matters.

## Thread State

The selected app-server endpoint defines live state. A loaded thread can be
`active`, `idle`, or in another server-reported state. A persisted thread can
still be inspected when it is not loaded, but it cannot be interrupted or
given input through that server until it is resumed.

`inspect` assembles metadata, loaded state, goal state, and recent turns through
separate requests. A running thread can advance between those requests. The
command compares the final turn summary with any full turn it loaded and avoids
combining activity with a newer lifecycle state, but the whole report is not an
atomic snapshot.

The goal section is read-only. Its counters and status remain separate from
app-server activity: an idle thread can still have an active goal.

## Turn History

Codex reconstructs `thread/turns/list` from materialized history on each page.
Rollback and compaction can change earlier turns, so a later scan may not match
an earlier one. Persisted turn items are also lossy; command output, tool
results, and some transient interactions are not guaranteed to be replayed.

Reconstruction cost grows with retained history, and concurrent readers share
app-server resources. If a history request times out, increase `--timeout`;
retrying immediately can add more contention.

`inspect` requests the newest one or two turns in one page. By default it keeps
full detail for the newest turn and reduces the previous turn to a summary;
`--brief` requests summaries only. `--items` limits printed items after the
newest full turn is transferred; it does not reduce that app-server response.

`items` exposes compact activity summaries. Plain `messages` lists conversation
previews; its JSON form preserves all retained text. `message` prints the
retained text of one exact user or agent message. These commands share ordering
and composite locators. Range selection, limit behavior, backend fallback, and
mutable-item caveats are described in
[materialized-history.md](materialized-history.md).

Exact message retrieval first tries native item pagination for the selected
turn and falls back to full turn reconstruction when that store does not
support it. Non-text user inputs and message metadata are not part of the
printed text.

Turn timestamps describe turn boundaries. Persisted message and activity items
do not provide absolute item timestamps, so threadctl does not invent them.

## Context State

For a local Unix endpoint, `inspect` reads the newest native token-count and
compaction records from the rollout path reported by `thread/read`. Remote
endpoints omit this local-file view rather than assuming the server path exists
on the client host. Context usage is the latest
recorded model exchange, not a continuous process measurement. It can remain
unchanged during a long command, and the report includes its observation time
and age for that reason.

If a compaction record is newer than the latest token count, threadctl omits the
old context value until Codex persists a post-compaction observation.

The remaining percentage follows Codex's user-controllable context calculation,
which subtracts the fixed 12,000-token baseline used by Codex 0.144 before
rounding. It is an orientation value, not the automatic compaction threshold.

Compaction window numbers come from persisted compaction records. Goal token
usage is cumulative across context windows and is unrelated to this context
measurement. Context fields are omitted when the rollout or relevant records
are unavailable.
