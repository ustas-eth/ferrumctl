# ferrumctl

Small Unix-style control tools for Codex agent workflows.

`ferrumctl` is the repository umbrella. It does not install a wrapper command.
Use the tools separately and compose them with the shell:

- `codex-goalctl` reads and changes persisted Codex thread goals.
- `codex-threadctl` discovers and inspects threads and applies immediate,
  turn-scoped control.
- `codex-wakectl` waits for conditions and schedules durable thread input.
- `codex-readcov` counts file-read actions from Codex rollout transcripts.

The optional Codex plugins add skills that explain when agents should use each
command. They do not change CLI behavior.

## Install

```sh
git clone https://github.com/ustas-eth/ferrumctl
cd ferrumctl

uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-threadctl
uv tool install ./packages/codex-wakectl
cargo install --locked --path ./packages/codex-readcov
```

Install one package at a time if you only need one command.

## Codex Plugins

Install the optional skills from the root marketplace:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-goalctl@ferrumctl
codex plugin add codex-threadctl@ferrumctl
codex plugin add codex-wakectl@ferrumctl
codex plugin add codex-readcov@ferrumctl
```

The marketplace manifest is [.agents/plugins/marketplace.json](.agents/plugins/marketplace.json).

## App Server

`codex-threadctl` and `codex-wakectl` use sessions connected to a shared
app-server:

```sh
codex app-server --listen unix://
codex --remote unix://
codex-threadctl loaded
```

For daily use, keep the Codex flags you normally use and add `--remote
unix://` to that shortcut, for example `alias x='codex --remote unix://'`.

## What You Can Do

Find recent sessions or retained subagent threads:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-threadctl list --limit 10
codex-threadctl list --parent "$SELF" --limit 5
codex-threadctl search "decision text" --limit 10
```

Assign durable work, wake the worker, then inspect its state and recorded read
actions:

```sh
WORKER=thread-id
MAIN=main-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json
codex-goalctl replace "$WORKER" "Review this package and mark the goal complete."
codex-threadctl start "$WORKER" "A goal was assigned. Call get_goal and proceed."
codex-threadctl inspect "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

Resume a main thread when a worker goal reaches a terminal status:

```sh
codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Worker goal reached a terminal status. Inspect it."
```

Schedule a self-reminder from a loaded Codex session:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 30m --to "$SELF" "Time check. Review progress."
```

Find expected files not present in a read list:

```sh
find packages -type f | sort > all.txt
codex-readcov delta worker.before.json packages --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

Process queued wakes with `codex-wakectl run`, or install the user timer:

```sh
codex-wakectl systemd install --interval 30s
```

The default wake queue is shared for the host user. Keep job ids for wakes you
create, and do not cancel jobs owned by other workflows.

More combinations are in [docs/coordination-recipes.md](docs/coordination-recipes.md).

## Layout

```text
packages/
  codex-goalctl/
  codex-threadctl/
  codex-wakectl/
  codex-readcov/
```

Each package keeps its own README, tests, package metadata, and Codex plugin.
Repository-level agent instructions are in [AGENTS.md](AGENTS.md).

## Documentation

Package READMEs are short landing pages. Low-level docs live beside each
package. Shared docs:

- [docs/coordination-principles.md](docs/coordination-principles.md)
- [docs/coordination-recipes.md](docs/coordination-recipes.md)
- [docs/operational-caveats.md](docs/operational-caveats.md)

Selected docs are copied into skill `references/` so installed Codex skills can
load details without requiring a repo checkout. Regenerate or check those copies
from the repo root:

```sh
python3 scripts/sync-skill-references.py
python3 scripts/sync-skill-references.py --check
```

## Development

```sh
scripts/check.sh
scripts/codex-smoke.sh
```

`scripts/check.sh` is the normal pre-commit check. `scripts/codex-smoke.sh` is
the local compatibility probe to run after Codex upgrades; it uses a temporary
`CODEX_HOME` and `XDG_STATE_HOME`, starts only its own app-server, and cleans up
after itself.
