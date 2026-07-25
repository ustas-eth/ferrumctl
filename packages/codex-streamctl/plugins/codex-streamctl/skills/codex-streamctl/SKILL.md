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

For sustained collaboration, use the stream after meaningful blocks of work.
A checkpoint should carry evidence, a question that can change the next step,
or the plan agreed for the next block. It should not be a routine status or
receipt.

## Patterns

Create one stream for an exchange:

```sh
STREAM=$(codex-streamctl create --label "design review")
```

Append a record. `CODEX_THREAD_ID` is used when `--author` is omitted:

```sh
POSITION=$(codex-streamctl append "$STREAM" \
  "The retry result rules out parser order. I will test transaction scope next." --json |
  jq -r .position)
```

Reply to a known position:

```sh
codex-streamctl append "$STREAM" --reply-to "$POSITION" \
  "That changes the next step: I will test cancellation; check the public contract."
```

When `CODEX_THREAD_ID` is set, read the next entries after your
acknowledgement:

```sh
codex-streamctl list "$STREAM" --json
```

Process every returned entry in order. Only afterward, acknowledge
`.lastPosition` from that exact result:

```sh
codex-streamctl ack "$STREAM" --through LAST_POSITION
```

Use `--after POSITION` for an explicit one-off range without changing a reader
acknowledgement or inferring a reader. Use `--limit 0` when the complete
selected interval is needed. If no entries are returned, there is nothing to
acknowledge.

When the `codex-threadctl` skill is also available, announce the highest
committed position when peer attention is useful:

```sh
codex-threadctl notify "$PEER" \
  "Stream $STREAM has a checkpoint through $POSITION; read after your current work step."
```

If the peer is known to be loaded and idle, `codex-threadctl wake "$PEER"` can
start its next turn without adding another message.

The append is authoritative. A notice can enter active reasoning at a later
model step, so batch nearby appends instead of notifying each one. Missing,
delayed, reordered, or duplicate notices are reconciled by listing from the
reader acknowledgement. When work should pause until the peer responds, say so
briefly in the notice and keep the substantive question in the stream.

## Conventions

- Use a stream for small collaboration records. Keep large evidence, generated
  output, and source changes in normal files or version control.
- `CODEX_THREAD_ID` is the default author and reader. Pass an explicit identity
  when acting for another participant or from a script.
- Treat positions as opaque stream-local cursors. Preserve the stream id with
  every saved position.
- Acknowledge only after processing every entry through that position,
  including entries authored by this reader.
- Treat author and reader values as provenance, not authentication.
- Do not assume an append wakes another agent. Use its native handle or an
  available thread-control skill when immediate attention is required.
- Keep notifications shorter than the stream entries they announce. Announce
  only the latest useful position; do not copy authoritative payloads, notify
  acknowledgements, or answer a notice without substantive stream content.
- A notice does not require abandoning a coherent work step. Unless further
  work depends on the peer's response, read it after the current work step.
  Between checkpoints, continue useful work instead of repeatedly listing the
  stream only to wait.
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
