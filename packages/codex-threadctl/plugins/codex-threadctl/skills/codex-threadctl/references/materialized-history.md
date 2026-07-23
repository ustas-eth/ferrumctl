<!-- Generated from packages/codex-threadctl/docs/materialized-history.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Materialized History

Codex represents retained thread history as ordered turns containing
`ThreadItem` records. User and agent messages are item types alongside commands,
file changes, tool calls, plans, reasoning, and context compactions.

This is Codex's materialized conversation view. It is not a complete rollout
event log.

## Projections

`items` lists compact activity summaries. It preserves native item types and
composite `(turn id, item id)` locators while omitting command output, diffs, and
other large payloads.

`messages` selects user and agent messages from the same ordered item sequence.
Plain output contains text previews; JSON preserves all retained text and
selected conversation fields. `message` prints the retained text of one exact
message by its composite locator. Non-text input parts are not included.

Filtering `items` to `userMessage` and `agentMessage` selects the same item
identities as `messages` over the same interval, but the output records are not
interchangeable.

## Ranges

Results are chronological. Selection happens in this order:

1. Restrict history with `--turn`, when present.
2. Resolve the exclusive `--after` and `--before` item boundaries.
3. Select item types or conversation messages.
4. Apply `--limit`.

Without `--after`, a positive limit returns the latest matching records. With
`--after`, it returns the earliest matching records after that boundary.
`--limit 0` returns the complete selected interval.

Bounds can name any materialized item, even when the final projection excludes
that type. This allows a compaction, command, or delivered request to delimit a
message query:

```sh
codex-threadctl items THREAD_ID \
  --type contextCompaction --limit 1

codex-threadctl messages THREAD_ID \
  --after TURN_ID ITEM_ID --limit 0 --json
```

Both parts of the locator are required because item ids can repeat across turns
or reconstructed compaction windows. A missing or ambiguous boundary is an
error; it is never treated as the beginning or end of history.

## Backends

Codex 0.144 defines experimental `thread/items/list` pagination, but classic
rollout-backed histories report that method as unsupported. Its response also
varies by Codex version: older servers return bare items, while newer servers
include each item's containing turn ID. Threadctl accepts both forms for an
exact `--turn` query and falls back to full `thread/turns/list` materialization
when needed.

Thread-wide queries use turn pagination for consistent turn attribution across
those versions. A paginated store that rejects full turn materialization and
returns the older bare-item response therefore requires `--turn`. JSON output
reports the selected `backend` and labels the `view` as `materialized`.

The fallback can transfer a large full turn even when compact output contains
only a few records. Range scans stop after resolving the necessary history, but
an old or missing boundary can still require many reconstructed pages.

## Snapshot Limits

Materialized items are snapshots, not a changefeed. A running command can keep
the same locator while its status or output changes, so an exclusive
`--after` query will not rediscover that mutation. Live monitors should overlap
the observed tail when updates to in-progress items matter.

An app-server can initially materialize a live request before it has caught up
with earlier history. The request's generated item id can then change as the
history is rebuilt. `start` therefore returns a stable client message id for
delivery correlation and the actual turn id for later response retrieval, not
the early item id as a range boundary.

Rollback or reconstruction can remove or change a saved boundary. Compaction
can alter older materialized history. Threadctl fails an unresolved locator
rather than silently selecting a different interval.

Items do not carry independent absolute timestamps. Reported timestamps belong
to their containing turn.
