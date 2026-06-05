# usctl

Small Unix-style control tools for agent workflows.

This repository is a neutral home for tools that help orchestrators supervise
agent sessions without turning simple operations into a single large app.

The current packages focus on Codex CLI:

- `codex-goalctl` reads and changes persisted Codex thread goals.
- `codex-wakectl` sends and schedules input turns for app-server-backed Codex
  threads.
- `codex-readcov` counts file read coverage from Codex rollout transcripts.

The binaries keep their explicit `codex-` names. `usctl` is the repository and
documentation umbrella, not a wrapper command.

## Layout

```text
packages/
  codex-goalctl/
  codex-wakectl/
  codex-readcov/
```

Each package keeps its own README, tests, packaging metadata, and plugin files.

## Install

Install the tools from their package directories:

```sh
uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-wakectl
cargo install --locked --path ./packages/codex-readcov
```

## Codex Plugins

The root marketplace manifest exposes all current Codex plugins:

```text
.agents/plugins/marketplace.json
```

After this repo is available on GitHub, install the marketplace source and then
install whichever plugins you want:

```sh
codex plugin marketplace add ustas-eth/usctl
codex plugin add codex-goalctl@usctl
codex plugin add codex-wakectl@usctl
codex plugin add codex-readcov@usctl
```

The plugins provide Codex skills for using the host commands. They do not change
the CLI behavior.

## Common Workflow

Use the tools together as separate Unix primitives:

```sh
codex-readcov snapshot "$THREAD_ID" > before.json
codex-goalctl replace "$THREAD_ID" "Review this code and mark the goal complete."
codex-wakectl send "$THREAD_ID" "A goal was assigned. Call get_goal and proceed."
codex-wakectl add goal "$THREAD_ID" --status complete,blocked,budgetLimited,usageLimited --to "$ORCH_ID" "Worker goal stopped. Inspect it."
codex-readcov delta before.json ./packages --limit 20
```

## Development

Run package checks from the package directories:

```sh
(cd packages/codex-goalctl && PYTHONPATH=src python3 -m unittest discover -s tests -v)
(cd packages/codex-wakectl && PYTHONPATH=src python3 -m unittest discover -s tests -v)
(cd packages/codex-readcov && cargo test)
```
