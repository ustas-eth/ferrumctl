---
name: streamctl
description: "Use when coding agents or host processes need a durable append-only exchange with stable positions and independent processed-through acknowledgements. Do not use for ordinary direct agent messaging, waking or starting an agent, retrieving conversation history, assigning work, scheduling input, or storing normal project artifacts."
---

# Streamctl

## Purpose

Use `streamctl` when shared records must outlive any one agent conversation. A
stream is an ordered sequence of immutable entries with one cumulative
acknowledgement per reader.

Streams provide publication and reading only. They do not notify participants,
start turns, authenticate identities, or decide how collaborators should
respond.

## Exchange Records

Create a stream and append a record:

```sh
STREAM=$(streamctl create --label "design review")
POSITION=$(streamctl append "$STREAM" \
  "The retry rules out parser order; I will test transaction scope next." \
  --json | jq -r .position)
```

Reply to a known entry:

```sh
streamctl append "$STREAM" --reply-to "$POSITION" \
  "I will test cancellation while you check the public contract."
```

When `CODEX_THREAD_ID` is set, it supplies the default author and reader. List
entries after that reader's acknowledgement:

```sh
streamctl list "$STREAM" --json
```

When entries are returned, process them in order, then acknowledge the non-null
`.lastPosition` from that exact result:

```sh
streamctl ack "$STREAM" --through LAST_POSITION
```

An empty result has nothing to acknowledge.

Use `--after POSITION` for an explicit one-off range that neither infers nor
changes a reader acknowledgement. Use `--limit 0` when the complete selected
interval is required.

## Add Attention Separately

An append is the durable publication boundary. If an immediate thread-control
skill is also available and peer attention is useful, announce only the latest
committed position:

```sh
codex-threadctl notify "$PEER" \
  "Stream $STREAM has a checkpoint through $POSITION."
```

Notification and wake remain separate from the stream. Missing, delayed,
reordered, or duplicate notices are reconciled by listing after the reader's
acknowledgement.

## Invariants

- Treat positions as opaque and local to one stream.
- Acknowledge only after processing every entry through that position,
  including entries authored by the same reader.
- Treat author and reader strings as provenance, not authentication.
- Keep large evidence, generated output, and source changes in normal files or
  version control.
- An ambiguous append may already have committed. Inspect the tail before
  retrying to avoid an accidental duplicate.
- Use `--state PATH` only when every participant intentionally shares that
  database.
- Use `--json` when another program will parse output.

## References

- Read `references/stream-semantics.md` for ordering, acknowledgements,
  identity, concurrency, state location, and failure boundaries.
- Read `references/coordination-principles.md` when composing streams with
  native handles, goals, immediate control, or scheduled wakes.
- Read `references/peer-workflows.md` for direct exchange, durable discussion,
  collaboration checkpoints, and deferred handoff.
