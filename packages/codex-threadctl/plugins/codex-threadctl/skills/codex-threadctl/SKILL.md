---
name: codex-threadctl
description: "Use when you need the host codex-threadctl command to inspect or immediately control a Codex CLI thread through app-server: discover loaded threads, check active or idle state, inspect recent activity and context, list or retrieve conversation messages, start input on an idle thread, steer one expected active turn, resume a persisted thread, or interrupt one exact turn. Do not use for future or conditional wakes, goal editing, file-read coverage, terminal injection, or agent spawning."
---

# Codex Threadctl

## Purpose

Use this skill when this session needs visibility into a Codex thread or must
apply an immediate thread operation through its thread id.

Assume `codex-threadctl` is installed. It reads app-server state and
materialized turn history, supplements local inspection with timestamped
rollout context, and exposes native start, steer, resume, and interruption
operations. It does not schedule future input, edit goals, measure read
coverage, or spawn agents.

## Choosing The Control Surface

Use native subagent input and result retrieval when this session owns the live
native handle. Use threadctl when the useful handle is a thread id or host-level
control is intentional.

Use `start` for a new turn on a target that appears idle. Use `steer` only with
the exact active turn id. Use wakectl instead when delivery must survive this
turn or wait for a later condition and its skill is available.

## Patterns

Discover threads loaded on the selected endpoint:

```sh
codex-threadctl loaded
codex-threadctl status THREAD_ID
```

Inspect recent work before deciding whether to wait or intervene:

```sh
codex-threadctl inspect THREAD_ID
codex-threadctl inspect THREAD_ID --brief
```

List recent conversation messages, then retrieve one complete message using
both ids from the list:

```sh
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

Start input on an idle thread:

```sh
codex-threadctl start THREAD_ID "A goal was assigned. Call get_goal and proceed."
```

Steer one known active turn:

```sh
codex-threadctl steer THREAD_ID TURN_ID "Focus on the failing test first."
```

Resume a persisted thread without sending input:

```sh
codex-threadctl resume THREAD_ID
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
- Treat `idle` as no running turn, not permission for unrelated work. An idle
  thread can retain an active goal.
- Read the result of `start`. Its idle check is not atomic; if another turn
  wins the race, the confirmed delivery mode can be `steered`.
- Always pass the turn id obtained from current inspection to `steer` and
  `interrupt`. Native expected-turn checks reject stale ids.
- Interruption without `--wait` reports `requested`, not completion. It does
  not pause an active goal or terminate background terminals.
- `resume` loads persisted state on the selected server. It does not start a
  turn or prove that another server is not controlling the same thread.
- Codex rejects direct app-server input to v2 subagents. Use their native
  parent handle instead of `start` or `steer`.
- Treat context percentage and age as orientation. Remote endpoints omit local
  rollout context, and long commands can run without a new model observation.
- Use turn id and item id together for message lookup.
- Treat materialized history as Codex's conversation view, not a raw immutable
  transcript.
- Use `--json` when another program will parse output.

## References

- Read `references/observation-semantics.md` when materialized history,
  timestamps, message lookup, context freshness, or snapshot consistency
  matters.
- Read `references/lifecycle-control.md` before relying on start, steering,
  resume, or interruption behavior.
- Read `references/coordination-principles.md` when composing immediate control
  with native handles, goals, scheduled wakes, coverage, or partial skill
  availability.
- Read `references/coordination-recipes.md` for command combinations involving
  worker review, checkpoints, peer handoffs, or external managers.
- Read `references/operational-caveats.md` when concurrent control, retries, or
  cross-surface consistency matters.
