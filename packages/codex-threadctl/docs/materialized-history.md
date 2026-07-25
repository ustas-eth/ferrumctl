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

Threadctl prefers `thread/items/list` for full item data. When each item carries
its containing turn ID, thread-wide queries preserve composite locators and use
summary turn pages only for status and timestamps. Classic rollout-backed
histories report item listing as unsupported; threadctl then falls back to full
`thread/turns/list` materialization.

Early Codex 0.144 paginated histories return bare items and do not expose turn
pages. An exact `--turn` query remains usable because the caller supplies the
missing attribution, although turn timestamps can be unavailable. Thread-wide
`items` and `messages` reject that combination instead of inventing locators.
`inspect` still reports thread, goal, and context state plus recent
unattributed items, with the limitation named in `historyError`.

JSON output reports the selected `backend` and labels item and message output
as `materialized`.

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
