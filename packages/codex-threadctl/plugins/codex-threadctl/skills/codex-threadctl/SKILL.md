---
name: codex-threadctl
description: "Use when you need the host codex-threadctl command to observe or control a Codex CLI thread through app-server: discover loaded threads, check active or idle state, inspect recent activity, goal and context state, list or retrieve conversation messages, interrupt an active turn, or compact an idle thread. Do not use for sending input, scheduling wakes, editing goals, file-read coverage, terminal injection, or spawning agents."
---

# Codex Threadctl

## Purpose

Use this skill when this session needs visibility into a Codex thread or must
apply an explicit thread lifecycle action.

Assume `codex-threadctl` is installed on the host. It reads thread state and
materialized turn history through a selected app-server, supplements inspection
with persisted context records, and can interrupt or compact loaded threads. It
does not send input, edit goals, inspect file-read coverage, or spawn agents.

## Model

- Loaded state says whether the selected app-server owns live control.
- Thread status says whether a turn is running now.
- Goal status describes durable assignment state.
- Turn history shows recent messages and structured activity.
- Context state is a timestamped observation of the latest model exchange.

These values are fetched from different records and are not one atomic
snapshot.

## Patterns

Discover threads loaded on the selected endpoint:

```sh
codex-threadctl loaded
```

Check only loaded and active/idle state:

```sh
codex-threadctl status THREAD_ID
```

Inspect recent work before deciding whether to wait or intervene:

```sh
codex-threadctl inspect THREAD_ID
```

Use the summary view when status and recent responses are enough:

```sh
codex-threadctl inspect THREAD_ID --brief
```

List the recent conversation, then retrieve one complete message with both ids
from the list:

```sh
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

Use `messages --limit 1` when only the newest conversational response or input
matters. Use `--limit 0` only when the full materialized history is deliberate.

Interrupt a known active turn:

```sh
codex-threadctl interrupt THREAD_ID
```

Compact only after the thread is idle and any active goal is paused:

```sh
codex-threadctl compact THREAD_ID
```

Use `--endpoint unix://PATH` when the target is attached to a non-default
app-server. Use `CODEX_THREAD_ID` for this thread's identity when available:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-threadctl inspect "$SELF"
```

## Conventions

- Inspect unfamiliar work before interrupting, compacting, steering, or
  reassigning it.
- Treat `idle` as no running turn, not as permission for unrelated work. An
  idle thread can retain an active goal.
- Treat the context percentage and age as orientation. A long command can run
  without changing the latest model-exchange record.
- Use the turn id and item id together. Item ids alone can repeat after another
  turn or compaction.
- `messages` lists the first user and final or latest agent message per turn;
  use full `inspect` for intermediate activity in the newest turn.
- Treat message history as Codex's materialized conversation view, not a raw or
  immutable transcript.
- Prefer native subagent result retrieval when this session owns the live
  native handle. Use threadctl when the useful handle is a thread id or host
  visibility is the intended path.
- Interrupt only after the decision to stop current work. Interruption does not
  pause an active goal.
- Do not compact while another controller may start work. The idle check and
  native compaction request are not atomic.
- Use `--json` when another program will parse output.

## References

- Read `references/observation-semantics.md` when materialized history,
  timestamps, message lookup, context freshness, or snapshot consistency
  matters.
- Read `references/lifecycle-control.md` before relying on interruption or
  manual compaction behavior.
- Read `references/coordination-principles.md` when composing observation with
  native controls, goals, wakes, coverage, or partial skill availability.
- Read `references/coordination-recipes.md` for command combinations involving
  worker review, checkpoints, peer handoffs, or external managers.
- Read `references/operational-caveats.md` when concurrent control, retries, or
  cross-surface consistency matters.
