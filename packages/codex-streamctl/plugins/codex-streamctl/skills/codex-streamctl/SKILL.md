---
name: codex-streamctl
description: "Use when you need a durable append-only exchange shared with another coding agent or host process: create a stream, append an immutable entry, read entries after a stable position or reader acknowledgement, reply to an entry, or advance your processed-through cursor. Do not use for ordinary native subagent messaging, waking or starting a Codex thread, retrieving a thread transcript, assigning goals, scheduling work, or storing normal project artifacts."
---

# Codex Streamctl

## Purpose

Use this skill when collaboration needs durable shared records outside any one
agent's conversation. Assume `codex-streamctl` is installed.

A stream is an ordered sequence of immutable entries with one cumulative
acknowledgement per reader. It does not notify participants, start their turns,
or decide how they should respond.

## Patterns

Create one stream for an exchange:

```sh
STREAM=$(codex-streamctl create --label "design review")
```

Append a record. `CODEX_THREAD_ID` is used when `--author` is omitted:

```sh
POSITION=$(codex-streamctl append "$STREAM" \
  "I reproduced the race; inspect commit abc123." --json |
  jq -r .position)
```

Reply to a known position:

```sh
codex-streamctl append "$STREAM" --reply-to "$POSITION" \
  "Confirmed. The state check must move into the transaction."
```

Read the next entries after your acknowledgement, process them in order, then
acknowledge the complete returned prefix:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
ENTRIES=$(codex-streamctl list "$STREAM" --reader "$SELF" --json)
THROUGH=$(printf '%s\n' "$ENTRIES" | jq -er .lastPosition)
# Process every returned entry before advancing the cursor.
codex-streamctl ack "$STREAM" --reader "$SELF" --through "$THROUGH"
```

Use `--after POSITION` for an explicit one-off range without changing a reader
acknowledgement. Use `--limit 0` when the complete selected interval is needed.
If no entries are returned, there is nothing to acknowledge.

When the `codex-threadctl` skill is also available, a committed append can be
followed by a short advisory notice and an optional idle wake:

```sh
codex-threadctl notify "$PEER" \
  "Stream $STREAM has unread entries through $POSITION."
codex-threadctl wake "$PEER"
```

The append is authoritative. Missing or duplicate notices are reconciled by
listing from the reader acknowledgement.

## Conventions

- Use a stream for small collaboration records. Keep large evidence, generated
  output, and source changes in normal files or version control.
- Treat positions as opaque stream-local cursors. Preserve the stream id with
  every saved position.
- Acknowledge only after processing every entry through that position,
  including entries authored by this reader.
- Treat author and reader values as provenance, not authentication.
- Do not assume an append wakes another agent. Use its native handle or an
  available thread-control skill when immediate attention is required.
- Keep notifications shorter than the stream entry they announce. Do not copy
  the authoritative payload into both surfaces.
- An ambiguous append may have committed. Inspect the tail before retrying, or
  a duplicate entry can be created.
- Use `--state PATH` only when every participant is intentionally using the
  same database.
- Use `--json` when another program will parse output.

## References

- Read `references/stream-semantics.md` when ordering, acknowledgement,
  identity, concurrency, state location, or failure boundaries matter.
- Read `references/coordination-principles.md` when composing streams with
  native handles, goals, immediate control, scheduled wakes, or partial skill
  availability.
- Read `references/coordination-recipes.md` for command combinations involving
  peer discussion, review, handoffs, or external managers.
- Read `references/operational-caveats.md` when concurrent control, retries, or
  cross-surface consistency matters.
