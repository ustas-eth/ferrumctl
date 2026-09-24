---
name: codex-threadctl
description: "Use to discover Codex threads, inspect their state or retained history beyond native results, create independently controlled roots, update thread settings, or apply immediate control through a thread id or canonical task name such as /root/reviewer. Prefer native tools for ordinary messaging, lifecycle control, and waiting when this session owns the live child. Do not use for future conditions, goal editing, terminal keystrokes, or native subagent spawning."
---

# Codex Threadctl

## Purpose

Use `codex-threadctl` to create an independently controlled root thread, observe
persisted Codex state, or apply a supported immediate operation through a
thread id or canonical task name such as `/root/reviewer`. It combines
persisted relationships and materialized history with live state from a
selected app-server.

Use native subagent tools for ordinary direct messages, lifecycle control,
waiting, and result retrieval when this session owns the live handle. Use
`notify` when authoritative content already exists elsewhere and a loaded target
only needs advisory context without starting or steering a turn. Use other
threadctl operations when only a thread id remains, host-level control is
intentional, or retained state beyond the native result is needed.

## Choose Ownership

Use a native subagent when this session should own its lifecycle and receive its
result. Current Codex rejects direct `start`, `steer`, `wake`, and `notify` for
parent-owned v2 children; control them through their native parent handle.
Task-name resolution and resume do not transfer that ownership.

When another thread or host process must control the worker directly, create an
independent root on the shared app-server from the outset:

```sh
WORKER=$(codex-threadctl create --cwd "$PWD")
```

`create` connects to the selected existing app-server (`unix://` by default); it
does not launch a server or a turn. It prints only the new thread id and adds one
short `threadctl` advisory item so the root is persisted before its first turn.
The new root has no native parent handle, canonical task name, or automatic
result return; use its thread id for later state and control operations.

The root uses the app-server's model, provider, reasoning, context, and
permission defaults, not settings inherited from this thread. Choose creation
overrides from the assignment and supervision model:

- Pass `--model MODEL_ID` when a model is required, adding `--model-provider`
  only for a non-default provider. A native subagent role name is not a model
  id; its role configuration does not apply. Pass `--effort` when reasoning
  effort matters.
- Use `--config-file FILE` for native Codex settings beyond the dedicated flags,
  such as worker-specific skills or context size. Explicit flags win. Retain the
  caller-local TOML file and reapply it on unloaded-thread `resume`; it is not a
  saved profile binding or a live `configure` option. Read the lifecycle reference
  when choosing file settings or relying on their persistence.
- Check that permission and approval defaults suit the work. Without an
  approval-capable client, `--approval-policy never` makes disallowed operations
  fail instead of waiting; it does not grant access.
- Use `--permission-profile NAME` only when the assignment or established host
  configuration already names that Codex filesystem and network policy. It is
  not a general configuration profile or native agent role. Do not search for
  or invent one as a prerequisite.
- Use `--dangerously-bypass-approvals-and-sandbox` only when the new root itself
  is deliberately authorized for unrestricted host access. This thread's access
  does not provide that authorization.

## Observe A Thread

Choose the narrowest useful view:

- `list` and `search` discover persisted threads without loading them.
- `agents` lists a spawned tree; `resolve` maps one canonical task name to a
  thread id.
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

Within the current spawn tree, `CODEX_THREAD_ID` scopes canonical task names
beginning with `/root`. Otherwise pass `--tree THREAD_ID`, where the id can
belong to any member of that tree. Threadctl commands that take a thread id
accept the same canonical name form. If a name is missing or was reused by
multiple persisted agents, resolution fails instead of guessing. Use an
unambiguous name directly for an immediate threadctl operation; resolve and
retain the thread id when another package requires one or the reference must
remain attached to that conversation.

## Choose Immediate Control

- `start` sends input to a loaded target with no running turn, including one
  whose preceding turn ended in `systemError`.
- `steer` sends input to one exact active regular turn.
- `notify` injects advisory agent context without starting a turn.
- `wake` starts an empty turn on a loaded `idle` or `systemError` target; an
  active target receives nothing.
- `resume` loads persisted state without adding a user message. It can continue
  an active goal, so `--continue-goal` is required. If settings must change before
  continuation, pass the overrides in this command while the thread is unloaded.
- `configure` updates a loaded thread's model, effort, permission profile, or
  approval policy for subsequent turns without starting or interrupting work.
- `interrupt` requests interruption of one exact turn.
- `terminate-terminal` targets one exact process from a current terminal
  listing.

Use a scheduled wake instead when attention must survive the current turn or
wait for a future condition and the corresponding skill is available.

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
codex-threadctl configure THREAD_ID --model MODEL_ID --effort high
```

Use `CODEX_THREAD_ID` for this thread's identity when available. For `notify`,
omit `--from` unless a host process or deliberate role identity needs another
label. Pass `--endpoint unix://PATH` when the target is loaded on a non-default
server.

## Observation Boundaries

- Live state belongs to the selected app-server. `notLoaded` does not say that
  a thread completed or is absent from another server.
- `idle` means that no turn is running. It does not grant ownership of the
  thread or exclude an active persisted goal.
- `systemError` means that the preceding turn stopped through a system failure.
  The thread remains loaded and can accept a new `start` or `wake`; inspect the
  returned turn to learn whether execution failed again.
- Persisted spawn relationships can include closed agents whose native handles
  no longer exist.
- Search snippets and compact message output are orientation aids. Use
  `message` or JSON output when complete retained text matters.
- Materialized history is Codex's conversation view, not an immutable event
  log. Use turn id and item id together; do not treat an item observed during
  an active turn as a durable checkpoint.
- Context percentage and age are recorded observations rather than continuous
  measurements.
- `inspect` separates server metadata from last-recorded turn settings. Check
  their time and turn id before treating them as evidence of a configuration
  change. A history error leaves other available observations intact.

## Control Boundaries

- `create` confirms that app-server returned a new root identity, not that any
  work ran. If its outcome is uncertain, inspect recent threads before retrying.
- JSON `permissionRequest` repeats the values submitted during `create`; never
  describe it as an observed runtime policy. Creation and resume return server
  `settings`; `configure` confirms acceptance, not execution under those settings.
- Except for `resume`, the target must be loaded on the selected app-server for
  live control.
- `start` has a non-atomic stopped-state check. Read its confirmed delivery mode
  because input can be steered into a turn that won the race.
- `notify` reports app-server acceptance and a raw agent-message id. It does not
  prove timing, model receipt, or action, and it does not wake the target.
- Pass a currently observed turn id to `steer` and `interrupt`. Interruption
  without `--wait` confirms only the request, not terminal completion.
- Use process and item ids from the same current `terminals` result for
  `terminate-terminal`.
- When input could be mistaken for direct human instruction, label its logical
  source naturally. A label is context, not authentication or added authority.

An uncertain submission may already have taken effect. Inspect before retrying.
Use `--json` when another program needs exact identifiers or outcomes.

## References

Routine observation and one confirmed immediate operation need no further
reference.

- Read `references/observation-semantics.md` when interpreting freshness,
  timestamps, context observations, or a multi-source snapshot.
- Read `references/materialized-history.md` when exact ranges, pagination,
  mutable item ids, or complete retained text matter.
- Read `references/lifecycle-control.md` when choosing worker configuration or
  skill settings, changing resume settings, automating immediate control, or
  reconciling an ambiguous control outcome.
- Read `references/permission-profiles.md` when choosing or interpreting a
  named profile, checking configuration precedence, or diagnosing unexpected
  access or missing worker instructions.
- Read `references/agent-trees.md` when task name resolution, name reuse, or
  native input ownership affects a decision.
- Read `references/coordination-principles.md` when designing a workflow across
  multiple ferrumctl state or control surfaces.
- Read `references/worker-workflows.md` when designing sustained worker
  supervision, checkpoints, or reviewer chains.
- Read `references/peer-workflows.md` when setting up durable peer discussion or
  handoff.
- Read `references/host-automation.md` when a script or external process manages
  threads.
