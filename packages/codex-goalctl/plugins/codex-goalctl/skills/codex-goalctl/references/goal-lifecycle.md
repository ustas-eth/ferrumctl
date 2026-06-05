<!-- Generated from packages/codex-goalctl/docs/goal-lifecycle.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Goal Lifecycle

`codex-goalctl` manages persisted Codex thread goals through `codex app-server`.
It does not spawn agents, send chat input, or wake a sleeping thread.

## Primitives

Read the current goal:

```sh
codex-goalctl get THREAD_ID
```

Edit the existing goal in place:

```sh
codex-goalctl update THREAD_ID "same goal, new wording"
codex-goalctl update THREAD_ID --status paused
codex-goalctl update THREAD_ID --token-budget 50000
```

Use `update` when existing usage and time counters should be preserved.

Start a fresh goal:

```sh
codex-goalctl replace THREAD_ID "new objective"
```

Use `replace` for a new assignment because it resets counters. `replace` is a
clear-then-set operation; the app-server does not expose an atomic reset
primitive. If preserving the old goal on failure matters more than resetting
counters, use `update`.

Clear the goal:

```sh
codex-goalctl clear THREAD_ID
```

## Waking

Goal writes do not reliably wake a CLI-owned thread. After assigning a goal,
send a normal input turn when the worker should act immediately:

```text
A goal was assigned. Call get_goal and proceed.
```

Use `codex-wakectl send` for app-server-backed sessions.

## Notes

- For v1 Codex subagents, the `spawn_agent` result's `agent_id` is the thread id.
- Use `--json` when another program will parse output.
- Pass `--timeout` for slow app-server calls.
