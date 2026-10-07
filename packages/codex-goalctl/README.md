# codex-goalctl

`codex-goalctl` reads and changes persisted Codex thread goals.

Use it when one session, script, or agent needs to inspect or assign durable
goal state for another Codex thread.

It reuses the usual shared app-server when that server holds the target,
including live goal accounting. Otherwise it starts a short-lived server to
access persisted state.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-goalctl
```

From this package directory:

```sh
uv tool install .
```

## Examples

Set a fresh goal with reset counters:

```sh
codex-goalctl replace THREAD_ID "Review this package and mark the goal complete."
```

Check or edit the current goal:

```sh
codex-goalctl get THREAD_ID
codex-goalctl update THREAD_ID "same goal, new wording"
codex-goalctl update THREAD_ID --status paused
codex-goalctl update THREAD_ID --clear-token-budget
codex-goalctl clear THREAD_ID
```

Change a worker's budget:

```sh
codex-goalctl update THREAD_ID --token-budget 500000
```

Use `--endpoint` for a worker on a different server, or `--standalone` to force
persisted-only access. The owning server may start an idle active goal itself;
arm completion watches before activation when using them.

Canonical task names returned by native subagent tools are not goal identifiers.
When threadctl is available, resolve one for a goal read:

```sh
WORKER=$(codex-threadctl resolve /root/reviewer)
codex-goalctl get "$WORKER"
```

Current Codex rejects external goal changes to parent-owned v2 children. Give
them assignments through their native parent workflow. For direct external goal
control, create an independent root first:

```sh
WORKER=$(codex-threadctl create --cwd "$PWD")
codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete."
```

When work still needs starting, continue a native child through its parent
handle. For an independent root, when threadctl is installed:

```sh
codex-threadctl wake "$WORKER" --resume
```

This continues from the goal without adding another user instruction. If the
worker needs its creation configuration on cold loading, reapply that file with
`--config-file FILE`.

Use `--json` when another program will parse output.

More detail:

- [docs/goal-lifecycle.md](docs/goal-lifecycle.md)
- [docs/app-server-boundaries.md](docs/app-server-boundaries.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-goalctl@ferrumctl
```

The skill lives at `plugins/codex-goalctl/skills/codex-goalctl/SKILL.md`.
