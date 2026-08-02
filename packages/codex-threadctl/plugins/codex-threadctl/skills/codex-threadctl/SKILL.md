---
name: codex-threadctl
description: "Use when a Codex thread id or v2 agent path is the useful handle for spawned-tree discovery, persisted history, current app-server state, retained messages, context or terminal visibility, or immediate control within native input-ownership boundaries, such as notify, wake, start, steer, resume, interrupt, or exact terminal termination. Prefer native subagent tools when this session owns the live handle. Do not use for future conditions, goal editing, read coverage, terminal keystrokes, or spawning."
---

# Codex Threadctl

## Purpose

Use `codex-threadctl` to observe persisted Codex thread state or apply a
supported immediate operation through a thread id or v2 agent path. It combines
persisted relationships and materialized history with live state from a
selected app-server.

Use native subagent tools for ordinary messaging, waiting, and result retrieval
when this session owns the live handle. Use threadctl when only a thread id
remains, host-level control is intentional, or retained state beyond the native
result is needed.

Threadctl does not schedule future input, edit goals, measure read coverage, or
spawn agents.

## Observe A Thread

Choose the narrowest useful view:

- `list` and `search` discover persisted threads without loading them.
- `agents` lists a spawned tree; `resolve` maps one v2 path to a thread id.
- `loaded` and `status` report state on the selected app-server.
- `inspect` gives a compact orientation across current state and recent work.
- `items` lists ordered activity summaries.
- `messages` lists retained conversation messages; `message` retrieves one
  exact message.
- `terminals` lists terminal processes still tracked by Codex.

```sh
codex-threadctl list --parent THREAD_ID --sort created --limit 5
codex-threadctl search "decision text" --limit 10
codex-threadctl agents
codex-threadctl resolve /root/reviewer
codex-threadctl inspect THREAD_ID --brief
codex-threadctl items THREAD_ID --limit 10
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
codex-threadctl terminals THREAD_ID
```

Use `items --after TURN_ID ITEM_ID` or `messages --after TURN_ID ITEM_ID` for an
exclusive range after a known composite locator. Use `--limit 0` when the full
selected interval is required.

Within the current spawn tree, `CODEX_THREAD_ID` scopes `/root` paths. Otherwise
pass `--tree THREAD_ID`, where the id can belong to any member of that tree.
Threadctl commands that take a thread id accept the same path form. If a path is
missing or was reused by multiple persisted agents, resolution fails instead of
guessing; keep the resolved thread id for durable state.

## Choose Immediate Control

- `start` sends input to a target that appears idle.
- `steer` sends input to one exact active regular turn.
- `notify` injects advisory agent context without starting a turn.
- `wake` starts an empty turn on a loaded idle target.
- `resume` loads persisted state without adding a user message.
- `interrupt` requests interruption of one exact turn.
- `terminate-terminal` targets one exact process from a current terminal
  listing.

Use scheduled input instead when delivery must survive the current turn or wait
for a future condition and the corresponding skill is available.

```sh
codex-threadctl start THREAD_ID \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
codex-threadctl steer THREAD_ID TURN_ID \
  "From coordinator: Focus on the failing test first."
codex-threadctl notify "$PEER" \
  "Stream $STREAM has a checkpoint through $POSITION."
codex-threadctl wake "$PEER"
codex-threadctl interrupt THREAD_ID TURN_ID --wait
codex-threadctl terminate-terminal THREAD_ID PROCESS_ID --item ITEM_ID
codex-threadctl resume THREAD_ID --continue-goal
```

Use `CODEX_THREAD_ID` for this thread's identity when available. Pass
`--endpoint unix://PATH` when the target is loaded on a non-default server.

## Observation Boundaries

- Live state belongs to the selected app-server. `notLoaded` does not say that
  a thread completed or is absent from another server.
- `idle` means that no turn is running. It does not grant ownership of the
  thread or exclude an active persisted goal.
- Persisted spawn relationships can include closed agents whose native handles
  no longer exist.
- Search snippets and compact message output are orientation aids. Use
  `message` or JSON output when complete retained text matters.
- Materialized history is Codex's conversation view, not an immutable event
  log. Use turn id and item id together; do not treat an item observed during
  an active turn as a durable checkpoint.
- Context percentage and age are recorded observations rather than continuous
  measurements.

## Control Boundaries

- Except for `resume`, the target must be loaded on the selected app-server for
  live control.
- `start` has a non-atomic idle check. Read its confirmed delivery mode because
  input can be steered into a turn that won the race.
- `notify` reports app-server acceptance only. It does not prove timing,
  persistence, model receipt, or action, and it does not wake the target.
- `wake` carries no instructions. It starts an empty turn only when the target
  is loaded and idle; an active target receives nothing.
- Pass a currently observed turn id to `steer` and `interrupt`. Interruption
  without `--wait` confirms only the request, not terminal completion.
- `resume` can continue an active goal, which is why `--continue-goal` is
  required.
- Use process and item ids from the same current `terminals` result for
  `terminate-terminal`.
- Codex rejects direct `start`, `steer`, and idle `wake` for parent-owned v2
  agents. Use their native parent handle for lifecycle control. Path-based
  inspection does not transfer that ownership. Advisory `notify` can affect
  active reasoning, but does not start or steer the child.
- When input could be mistaken for direct human instruction, label its logical
  source naturally. A label is context, not authentication or added authority.

An uncertain submission may already have taken effect. Inspect before retrying.
Use `--json` when another program needs exact identifiers or outcomes.

## References

- Read `references/observation-semantics.md` for discovery, search, app-server
  status, timestamps, context freshness, and snapshot consistency.
- Read `references/materialized-history.md` for item projections, ranges,
  pagination backends, and mutable history.
- Read `references/lifecycle-control.md` before relying on notification, wake,
  start, steering, resume, interruption, or terminal-process behavior.
- Read `references/agent-trees.md` for path scope, path reuse, input ownership,
  and scheduled conditions involving v2 agents.
- Read `references/coordination-principles.md` when composing immediate control
  with native handles, goals, streams, wakes, or coverage.
- Read `references/worker-workflows.md` for worker supervision, checkpoints, and
  reviewer chains.
- Read `references/peer-workflows.md` for direct exchanges, durable discussion,
  and handoffs.
- Read `references/host-automation.md` for scripts and external managers.
