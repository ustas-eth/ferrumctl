<!-- Generated from packages/codex-goalctl/docs/goal-lifecycle.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Goal Lifecycle

This reference describes how `codex-goalctl` changes persisted Codex thread
goals.

## Goal State

A goal belongs to a Codex thread. The app-server stores the objective, status,
optional token budget, and usage counters such as elapsed time and tokens used.

`codex-goalctl` does not decide task progress. It asks the app-server to read,
set, or clear goal fields; a running thread may later update its own goal state
through Codex.

Valid statuses are:

- `active`
- `paused`
- `blocked`
- `budgetLimited`
- `usageLimited`
- `complete`

Objectives are trimmed, must be non-empty, and are limited to 4000 characters.
Use `-` as the objective argument to read goal text from stdin.

## Primitives

Read the current goal. Text output is `STATUS<TAB>OBJECTIVE`; `--json` prints
the full goal object.

```sh
codex-goalctl get THREAD_ID
```

If no goal exists, text output prints `no goal` to stderr and exits non-zero.
JSON output prints `"goal": null` and exits successfully.

Edit the existing goal in place. Only supplied fields are changed.

```sh
codex-goalctl update THREAD_ID "same goal, new wording"
codex-goalctl update THREAD_ID --status paused
codex-goalctl update THREAD_ID --token-budget 50000
```

Use `update` when existing usage and time counters should be preserved. It
fails if no objective, status, or token budget is supplied.

Start a fresh goal.

```sh
codex-goalctl replace THREAD_ID "new objective"
codex-goalctl replace THREAD_ID "new objective" --token-budget 50000
```

Use `replace` for a new assignment because it resets counters. `replace` is a
clear-then-set operation; the app-server does not expose an atomic reset
primitive. If preserving the old goal on failure matters more than resetting
counters, use `update`.

`replace` defaults the new status to `active` unless `--status` is supplied.

Clear the goal. This removes the persisted goal state; it does not affect the
thread transcript or running process.

```sh
codex-goalctl clear THREAD_ID
```
