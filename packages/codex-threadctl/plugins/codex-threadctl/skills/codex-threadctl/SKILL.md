---
name: codex-threadctl
description: "Use when the useful handle is a Codex thread id or persisted thread state is needed: use the host codex-threadctl command through app-server to discover or search stored sessions and spawned threads unavailable through native handles, inspect current or ordered activity, context, or compaction state, retrieve retained messages or what followed a known item, inspect running terminal processes, start input on an idle thread, steer one expected active turn, resume a persisted thread, interrupt one exact turn, or terminate one exact terminal process. Do not use for ordinary native subagent messaging, waiting, or result retrieval while this session owns the live handle; future or conditional wakes; goal editing; file-read coverage; terminal keystroke injection; or agent spawning."
---

# Codex Threadctl

## Purpose

Use this skill when this session needs visibility into a Codex thread or must
apply an immediate thread operation through its thread id.

Assume `codex-threadctl` is installed. It reads persisted thread relationships
and search results, app-server state, materialized item history, and running
terminal processes. It supplements local inspection with timestamped rollout
context and exposes native start, steer, resume, interruption, and exact
terminal termination. It does not schedule future input, edit goals, measure
read coverage, or spawn agents.

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
- Cross-thread input does not identify its logical sender. When the target
  could mistake it for direct human input, begin the message with a natural
  label such as `From coordinator:` or `From reviewer:`. Add `via
  threadctl` only when transport matters. A source label does not override
  existing instructions.
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
  parent handle instead of `start` or `steer`.
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
- For alternating peer discussion through thread ids, keep pushed thoughts
  concise and label them as advisory. For substantial analysis, leave the
  response in the responder's thread and retrieve that exact turn instead of
  copying it into another thread as user input.
- Use `--json` when another program will parse output.

## References

- Read `references/observation-semantics.md` when persisted discovery or search,
  app-server status, materialized history, timestamps, message lookup, context
  freshness, or snapshot consistency matters.
- Read `references/materialized-history.md` when item types, range boundaries,
  filtering and limits, backend fallback, or mutable item behavior matters.
- Read `references/lifecycle-control.md` before relying on start, steering,
  resume, interruption, or terminal-process behavior.
- Read `references/coordination-principles.md` when composing immediate control
  with native handles, goals, scheduled wakes, coverage, or partial skill
  availability.
- Read `references/coordination-recipes.md` for command combinations involving
  worker review, checkpoints, peer discussion, handoffs, or external managers.
- Read `references/operational-caveats.md` when concurrent control, retries, or
  cross-surface consistency matters.
