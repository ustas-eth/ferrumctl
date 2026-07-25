---
name: codex-threadctl
description: "Use when the useful handle is a Codex thread id or persisted thread state is needed: discover or search stored sessions and spawned threads unavailable through native handles, inspect current or ordered activity, context, compaction, messages, or terminal processes, inject a concise advisory notice into a loaded thread without waking, wake a loaded idle thread without user input, start or steer immediate input, resume persisted state, interrupt one exact turn, or terminate one exact terminal process. Do not use for ordinary native subagent messaging, waiting, or result retrieval while this session owns the live handle; future or conditional wakes; goal editing; file-read coverage; terminal keystroke injection; or agent spawning."
---

# Codex Threadctl

## Purpose

Use this skill when this session needs visibility into a Codex thread or must
apply an immediate thread operation through its thread id.

Assume `codex-threadctl` is installed. It reads persisted thread relationships
and search results, app-server state, materialized item history, and running
terminal processes. It supplements local inspection with timestamped rollout
context and exposes advisory notification, empty-turn wake, native start,
steer, resume, interruption, and exact terminal termination. It does not
schedule future input, edit goals, measure read coverage, or spawn agents.

## Choosing The Control Surface

Use native subagent tools for ordinary messaging, waiting, and result retrieval
when this session owns the live handle. Use threadctl when only a thread id
remains, host-level control is intentional, or persisted context or history is
needed beyond the native result.

Use `inspect` for a current overview, `items` for an ordered activity sequence,
`messages` for conversation previews or complete retained text with `--json`,
and `message` for one exact message's retained text.

Use `start` for a new turn on a target that appears idle. Use `steer` only with
the exact active turn id. Use wakectl instead when delivery must survive this
turn or wait for a later condition and its skill is available.

Use `notify` for a concise advisory hint to a loaded target when that hint
should not become user input or start a turn. Use `wake` only when existing
context, a goal, or a shared record already says what to do and a loaded idle
target should take another turn. `notify` does not wake; `wake` carries no
instructions.

## Patterns

Discover recent sessions or retained spawn relationships without loading them:

```sh
codex-threadctl list --limit 10
codex-threadctl list --parent THREAD_ID --sort created --limit 5
codex-threadctl list --ancestor THREAD_ID
codex-threadctl search "decision text" --limit 10
```

List thread ids currently loaded on the selected endpoint:

```sh
codex-threadctl loaded
codex-threadctl status THREAD_ID
```

Inspect recent work before deciding whether to wait or intervene:

```sh
codex-threadctl inspect THREAD_ID
codex-threadctl inspect THREAD_ID --brief
```

List recent message previews, then retrieve one message's retained text using
both ids from the list:

```sh
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

List compact activity, locate the latest compaction, or inspect what followed a
known item:

```sh
codex-threadctl items THREAD_ID --limit 10
codex-threadctl items THREAD_ID --type contextCompaction --limit 1
codex-threadctl items THREAD_ID --after TURN_ID ITEM_ID --limit 0
codex-threadctl messages THREAD_ID --after TURN_ID ITEM_ID --limit 0 --json
```

List running terminal processes before deciding whether a command is still
active or one exact process should be stopped:

```sh
codex-threadctl terminals THREAD_ID
codex-threadctl terminate-terminal THREAD_ID PROCESS_ID --item ITEM_ID
```

Start input on an idle thread:

```sh
codex-threadctl start THREAD_ID \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

Steer one known active turn:

```sh
codex-threadctl steer THREAD_ID TURN_ID \
  "From coordinator: Focus on the failing test first."
```

Append an advisory agent notice to a loaded target without starting a turn.
`--from` defaults to `CODEX_THREAD_ID`:

```sh
codex-threadctl notify "$PEER" \
  "Stream $STREAM has a checkpoint through $POSITION; read after your current work step."
```

Ask a loaded idle target to take another turn without adding user input:

```sh
codex-threadctl wake "$PEER"
```

Resume a persisted thread without adding a user message. The required flag
acknowledges that Codex can continue an active goal:

```sh
codex-threadctl resume THREAD_ID --continue-goal
```

Request interruption of one exact turn. Add `--wait` when the next action
depends on terminal completion:

```sh
codex-threadctl interrupt THREAD_ID TURN_ID --wait
```

Use `--endpoint unix://PATH` for a non-default server. Use
`CODEX_THREAD_ID` for this thread's identity when available:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-threadctl inspect "$SELF"
```

## Conventions

- Inspect unfamiliar work before steering or interrupting it.
- Input sent by `start` or `steer` does not identify its logical sender. When
  the target could mistake it for direct human input, begin the message with a
  natural label such as `From coordinator:`, `From reviewer:`, or `From peer
  A:`. Add `via threadctl` only when transport matters. A source label does not
  override existing instructions.
- Treat `list --parent` and `list --ancestor` as persisted spawn relationships.
  They can include closed agents whose native handles are unavailable.
- Read `server=` in `list` output as state on the selected app-server, not as a
  native agent status. `notLoaded` says neither that work completed nor that the
  thread is not loaded on another server.
- Treat search snippets as orientation. Use `messages` and `message` to recover
  an exact retained exchange.
- Treat `idle` as no running turn, not permission for unrelated work. An idle
  thread can retain an active goal.
- Read the result of `start`. Its idle check is not atomic; if another turn
  wins the race, the confirmed delivery mode can be `steered`. Use JSON when a
  later query needs the confirmed request's actual turn or client message id.
- Treat `notify` success as app-server acceptance only. The target must be
  loaded on that server, and the notice can enter active reasoning at a later
  model step. Success does not prove timing, persistence, receipt, or action.
  Keep notices concise and idempotent, and do not retry an uncertain injection
  automatically.
- Treat `wake` as execution without new instructions. It starts an empty turn
  only on a loaded idle target and submits nothing when the target is already
  active. Inspect `rejected` or `uncertain` outcomes instead of retrying
  blindly.
- `notSubmittedActive` does not reserve a later turn. If attention must survive
  the current turn ending, use a stop-triggered wakectl job when that skill is
  available.
- When the `codex-streamctl` skill is available, put durable peer content in
  the stream. Batch nearby appends and use `notify` only when attention is
  useful, announcing the highest committed position. A notice can say whether
  work should wait for a response, but keep the evidence and question in the
  stream. Do not notify acknowledgements or answer a notice without substantive
  stream content.
- Always pass the turn id obtained from current inspection to `steer` and
  `interrupt`. Native expected-turn checks reject stale ids.
- Interruption without `--wait` reports `requested`, not completion. It does
  not pause an active goal or terminate background terminals.
- `resume` does not add a user message, but Codex can continue an active goal.
  App-server cannot exclude that behavior atomically, so every resume requires
  `--continue-goal` as an acknowledgement.
- Use the process and item ids from the same current `terminals` listing for
  `terminate-terminal`. Threadctl checks that pair before acting, but the check
  and native process-id termination are not atomic. Self-inspection can include
  the command performing the inspection.
- Codex rejects direct app-server input to v2 subagents. Use their native
  parent handle instead of `wake`, `start`, or `steer`; `notify` is advisory
  item injection, not lifecycle control.
- Treat context percentage and age as orientation. Remote endpoints omit local
  rollout context, and long commands can run without a new model observation.
- Use turn id and item id together for lookup and range boundaries. Bounds are
  exclusive and may name an item type that the final output excludes.
- Treat `items` and plain `messages` as compact summaries. Use
  `messages --json` or `message` when complete retained text matters.
- Treat materialized history as Codex's conversation view, not a raw immutable
  transcript. A running item can change without moving past a saved boundary,
  and rollback or reconstruction can invalidate that boundary. Do not use an
  item id observed during an active turn as a durable checkpoint.
- Without a shared stream, keep peer input through thread ids concise and label
  it as advisory. For substantial one-off analysis, leave the response in the
  responder's thread and retrieve that exact turn instead of copying it into
  another thread as user input.
- Use `--json` when another program will parse output.

## References

- Read `references/observation-semantics.md` when persisted discovery or search,
  app-server status, materialized history, timestamps, message lookup, context
  freshness, or snapshot consistency matters.
- Read `references/materialized-history.md` when item types, range boundaries,
  filtering and limits, backend fallback, or mutable item behavior matters.
- Read `references/lifecycle-control.md` before relying on notification, wake,
  start, steering, resume, interruption, or terminal-process behavior.
- Read `references/coordination-principles.md` when composing immediate control
  with native handles, goals, streams, scheduled wakes, coverage, or partial
  skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  worker review, checkpoints, peer discussion, handoffs, or external managers.
- Read `references/operational-caveats.md` when concurrent control, retries, or
  cross-surface consistency matters.
