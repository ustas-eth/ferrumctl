<!-- Generated from docs/peer-workflows.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Peer Workflows

These examples cover direct exchanges, durable peer discussion, and handoff
between coding agents. Use only the layers needed by the participants. In an
agent session, a command should have its corresponding skill unless the user
explicitly requested it.

## Direct Exchange

For a short exchange, use a native subagent handle when one participant owns
it. When only thread ids are available, immediate thread control can start the
recipient:

```sh
codex-threadctl start "$B" \
  "From peer A: Review the range semantics and reply with your conclusion."
```

Retrieve the answer through the native handle or from the exact turn returned
by `start`.

## Durable Discussion

Use one stream when substantive peer records must survive individual
conversations:

```sh
STREAM=$(codex-streamctl create --label "range review")
POSITION=$(codex-streamctl append "$STREAM" \
  "The half-open range avoids replaying the boundary. I will test rollback; check retry behavior." \
  --json | jq -r .position)
```

Place the stream id in each participant's existing context or durable
assignment. When peer attention is useful and immediate thread control is
available, announce only the highest committed position:

```sh
codex-threadctl notify "$B" \
  "Stream $STREAM has a checkpoint through $POSITION."
```

Notification is advisory and does not define stream order. If B is loaded and
idle, an empty wake can start its next turn without adding another message:

```sh
codex-threadctl wake "$B"
```

In B's thread, `CODEX_THREAD_ID` selects B's reader acknowledgement:

```sh
codex-streamctl list "$STREAM" --limit 0 --json
```

When entries are returned, B processes them in order and only then advances
through the non-null `.lastPosition` from that exact result:

```sh
codex-streamctl ack "$STREAM" --through LAST_POSITION
```

An empty result has nothing to acknowledge. Acknowledgement is already durable
reader state. It does not require a notice or a receipt entry. Missing, delayed,
reordered, or duplicate notices are reconciled by listing after the saved
acknowledgement.

## Collaboration Cadence

The stream imposes no conversation protocol. For joint reasoning, useful
checkpoints usually contain evidence, a decision that can change the next work,
or agreed ownership of the next step. Routine status and acknowledgement
traffic add little.

Participants can continue independent work between checkpoints. When one
cannot proceed without a reply, record that dependency in the stream and make
the attention notice explicit. A notice need not interrupt a coherent work
step.

## Deferred Handoff

When one loaded session should act after a host-visible condition, assign
durable work first when goal management is available, then schedule the event:

```sh
NEXT=next-thread-id

codex-goalctl replace "$NEXT" \
  "Continue from done.txt and complete the next step."

codex-wakectl add cmd --to "$NEXT" \
  "Automated event: Input is ready." -- test -f done.txt
```

Omit the goal when the wake message is deliberately the complete instruction.
Keep the predicate cheap and level-triggered so readiness remains observable
until the handoff is handled.
