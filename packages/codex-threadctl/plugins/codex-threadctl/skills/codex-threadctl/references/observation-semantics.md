<!-- Generated from packages/codex-threadctl/docs/observation-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Observation Semantics

This reference describes what `codex-threadctl` observes and where that view can
be incomplete or stale.

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

`inspect` loads the newest turn in full by default and the previous turn as a
summary. `--brief` requests summaries only. `--items` limits printed items after
the newest full turn is transferred; it does not reduce that app-server
response.

`messages` reads full turn pages and returns retained user and agent messages in
chronological order. `--limit 0` scans the full materialized history. Each
locator contains a turn id and item id because item ids can repeat across turns
or compaction windows.

`message` pages through full turns until it finds that pair, then prints the
complete message text retained by Codex. Codex 0.144 has no working item lookup
endpoint, so old message retrieval can still reconstruct a large rollout more
than once even though network output stays small.

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
