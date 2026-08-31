# Peer Workflows

These examples cover direct exchanges, durable peer discussion, and handoff
between coding agents. Use only the layers needed by the participants. In an
agent session, a command should have its corresponding skill unless the user
explicitly requested it.

## Direct Exchange

For a short exchange, use a native subagent handle when one participant owns
it. When the recipient is an independently controlled root and only thread ids
are available, immediate thread control can start it:

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
STREAM=$(streamctl create --label "range review")
POSITION=$(streamctl append "$STREAM" \
  "The half-open range avoids replaying the boundary. I will test rollback; check retry behavior." \
  --json | jq -r .position)
```

Place the stream id in each participant's existing context or durable
assignment. Once the stream is the authoritative exchange, keep substantive
peer content there. When an active peer accepts direct app-server injection,
would benefit from prompt attention, and immediate thread control is available,
announce only the highest committed position. The target can be a thread id or
an unambiguous canonical task name such as `/root/reviewer`:

```sh
codex-threadctl notify "$B" \
  "Stream $STREAM has a checkpoint through $POSITION."
```

Notification is advisory and does not define stream order. Current Codex
rejects it for parent-owned v2 children; use their native parent message path.
If B is idle and must act, start it through its native owner or use an empty
wake when B accepts direct input:

```sh
codex-threadctl wake "$B"
```

In B's thread, `CODEX_THREAD_ID` selects B's reader acknowledgement:

```sh
streamctl list "$STREAM" --limit 0 --json
```

When entries are returned, B processes them in order and only then advances
through the non-null `.lastPosition` from that exact result:

```sh
streamctl ack "$STREAM" --through LAST_POSITION
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
  -- test -f done.txt
```

Use `--input MESSAGE` instead when the delayed text itself is deliberately the
complete instruction. Keep the predicate cheap and level-triggered so
readiness remains observable until the handoff is handled.
