---
name: codex-streamctl
description: "Use when coding agents or host processes need an ordered durable exchange with stable positions and independent processed-through acknowledgements, including peer checkpoints that must remain available independently of native message history. Do not use when an ordinary direct message is sufficient, or for waking or starting a Codex thread, retrieving thread history, assigning work, scheduling input, or storing normal project artifacts."
---

# Codex Streamctl

## Purpose

Use `codex-streamctl` when an exchange needs a durable record independent of its
delivery channel, not merely because several agents are involved. A stream is
an ordered sequence of immutable entries with one cumulative acknowledgement
per reader. It does not notify participants, start turns, authenticate
identities, or decide how collaborators should respond.

A short direct exchange is usually better served by native messaging. Once a
stream is authoritative, keep substantive peer content there and use other
channels for attention or lifecycle control.

## Exchange Records

Create a stream and append a record:

```sh
STREAM=$(codex-streamctl create --label "design review")
POSITION=$(codex-streamctl append "$STREAM" \
  "The retry rules out parser order; I will test transaction scope next." \
  --json | jq -r .position)
```

Reply to a known entry:

```sh
codex-streamctl append "$STREAM" --reply-to "$POSITION" \
  "I will test cancellation while you check the public contract."
```

When `CODEX_THREAD_ID` is set, omit `--author` and `--reader`; it supplies a
stable per-thread identity. Every distinct reader string has an independent
acknowledgement. Override the default only when separate identities or deliberate
continuity across replacement threads are part of the workflow.

List entries after the current reader's acknowledgement:

```sh
codex-streamctl list "$STREAM" --json
```

When entries are returned, process them in order, then acknowledge the non-null
`.lastPosition` from that exact result:

```sh
codex-streamctl ack "$STREAM" --through LAST_POSITION
```

An empty result has nothing to acknowledge.

Use `--after POSITION` for an explicit one-off range that neither infers nor
changes a reader acknowledgement. Use `--limit 0` when the complete selected
interval is required.

## Add Attention Separately

An append is the durable publication boundary. If an immediate thread-control
skill is also available and an active peer would benefit from prompt attention,
announce only the latest committed position. `$PEER` may be a thread id or an
unambiguous canonical task name such as `/root/reviewer`:

```sh
codex-threadctl notify "$PEER" \
  "Stream $STREAM has a checkpoint through $POSITION."
```

Notification and wake remain separate from the stream. Missing, delayed,
reordered, or duplicate notices are reconciled by listing after the reader's
acknowledgement.

Use native messaging when the message itself is the exchange or controls the
recipient's lifecycle. If an idle recipient must act, start it through its
lifecycle owner; notification alone cannot do that.

## Invariants

- Treat positions as opaque and local to one stream.
- Acknowledge only after processing every entry through that position,
  including entries authored by the same reader.
- Treat author and reader strings as provenance, not authentication. Do not
  alternate identities for one participant unintentionally.
- Keep large evidence, generated output, and source changes in normal files or
  version control.
- An ambiguous append may already have committed. Inspect the tail before
  retrying to avoid an accidental duplicate.
- Commands under the same host user share the default database. Use another
  `--state PATH` only when the workflow deliberately selected it.
- Use `--json` when another program will parse output.

## References

Routine append, list, acknowledge, and notification operations need no further
reference.

- Read `references/stream-semantics.md` when reasoning about concurrency,
  identity continuity, custom state, or an ambiguous failure.
- Read `references/coordination-principles.md` when designing a workflow across
  multiple ferrumctl state or control surfaces.
- Read `references/peer-workflows.md` when setting up sustained collaboration,
  checkpoint cadence, or a deferred handoff.
