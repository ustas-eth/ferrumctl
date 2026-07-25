<!-- Generated from packages/codex-streamctl/docs/stream-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Stream Semantics

This reference describes the durable state exposed by `codex-streamctl`.

## Storage And Ordering

Each state database contains independent streams. A stream has an opaque id,
an optional label, and a contiguous sequence of immutable entries. SQLite
serializes appends to one stream and assigns each committed entry the next
positive integer position.

An append transaction records the entry and advances the stream tail together.
`--reply-to` can name only an existing position in the same stream. It is a
reference, not a branch or delivery instruction.

The default database is private to the host user. `--state` can select another
database; participants using different databases do not share state.

## Reader Acknowledgements

Each `(stream, reader)` pair has one cumulative acknowledgement. `list
--reader` begins after that position and returns entries in ascending order.
It includes entries authored by the reader because an acknowledgement means
the reader processed the complete stream through that position.
When both `--reader` and `--after` are omitted, `CODEX_THREAD_ID` supplies the
reader if it is set; otherwise listing begins at the first entry. `--after`
selects an explicit one-off range and does not infer a reader.

`--after` overrides the saved acknowledgement for one list operation without
changing it. `ack --through` advances the saved position monotonically.
Repeating an acknowledgement or requesting an older position is a successful
no-op. A position beyond the current tail is rejected.

One list operation reads the tail, reader cursor, and returned entries from the
same SQLite snapshot. JSON distinguishes `lastPosition`, the last entry
actually returned, from `tailPosition`, the stream tail in that snapshot.
`lastPosition` is null when no entries are returned; do not acknowledge in that
case. Otherwise acknowledge `lastPosition`; a limited result can end before the
tail.

An acknowledgement is application state. It does not prove that a model saw,
understood, or acted on an entry.

## Identity And Scope

Authors and readers are caller-supplied provenance strings, not authenticated
principals. Thread ids are useful identities, but the database does not verify
ownership, membership, or access.

Streams impose no participant count, topic model, or turn-taking protocol.
Their entries can represent peer discussion, review findings, handoffs, or
other small coordination records. Large artifacts and source changes remain
better suited to normal files and version control.

## Failure Boundaries

A successful append is the durable publication boundary. If a caller loses
the result after submission, retrying can append a duplicate because the
command has no idempotency key. Reconcile the stream tail before retrying an
ambiguous append.

Streams do not notify or wake participants. A separate transport can announce
the latest committed position, but that notice is advisory. Notice timing or
arrival order does not define stream order. Nearby appends can be announced
once at their highest position; acknowledgements need no notice because they
are already durable state. Readers recover from missing, delayed, reordered, or
duplicate notices by listing after their durable acknowledgement.

Appending, notifying, waking, and acknowledging are independent operations.
There is no cross-command transaction or automatic rollback between them.
