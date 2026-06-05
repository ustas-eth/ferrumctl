# ferrumctl

Small Unix-style control tools for agent workflows.

`ferrumctl` is the repository umbrella. It does not install a `ferrumctl` wrapper
command. The current binaries are Codex-specific and keep explicit names:

- `codex-goalctl` reads and changes persisted Codex thread goals.
- `codex-wakectl` sends and schedules input turns for app-server-backed Codex
  threads.
- `codex-readcov` counts file read coverage from Codex rollout transcripts.

Use the commands separately and compose them with the shell. The optional Codex
plugins add skills that explain common workflows; they do not change CLI
behavior.

## Install

```sh
git clone https://github.com/ustas-eth/ferrumctl
cd ferrumctl

uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-wakectl
cargo install --locked --path ./packages/codex-readcov
```

## Codex Plugins

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-goalctl@ferrumctl
codex plugin add codex-wakectl@ferrumctl
codex plugin add codex-readcov@ferrumctl
```

The marketplace manifest is [.agents/plugins/marketplace.json](.agents/plugins/marketplace.json).

## Full Workflow Setup

Start a shared app-server in one terminal:

```sh
codex app-server --listen unix://
```

Start or resume Codex sessions through that server:

```sh
codex --remote unix://
```

List loaded thread ids:

```sh
codex-wakectl loaded
```

## Common Workflow

See [docs/workflows/orchestrator-worker-loop.md](docs/workflows/orchestrator-worker-loop.md)
for the full loop.

```sh
WORKER=thread-id
ORCH=orchestrator-thread-id

codex-readcov snapshot "$WORKER" > before.json
codex-goalctl replace "$WORKER" "Review this code and mark the goal complete."
codex-wakectl add goal "$WORKER" --status complete,blocked,budgetLimited,usageLimited --to "$ORCH" "Worker goal stopped. Inspect it."
codex-wakectl send "$WORKER" "A goal was assigned. Call get_goal and proceed."
codex-readcov delta before.json ./packages --limit 20
```

Process queued wakes with `codex-wakectl run`, or install the user timer:

```sh
codex-wakectl systemd install --interval 30s
```

## Layout

```text
packages/
  codex-goalctl/
  codex-wakectl/
  codex-readcov/
```

Each package keeps its own README, tests, package metadata, and Codex plugin.
Repository-level agent instructions are in [AGENTS.md](AGENTS.md).

## Documentation

Package READMEs are short landing pages. Technical docs live beside each
package:

```text
packages/codex-goalctl/docs/
packages/codex-wakectl/docs/
packages/codex-readcov/docs/
docs/workflows/
```

Selected docs are copied into skill `references/` so installed Codex skills can
load details without requiring a repo checkout. Regenerate or check those copies
from the repo root:

```sh
python3 scripts/sync-skill-references.py
python3 scripts/sync-skill-references.py --check
```

## Development

```sh
(cd packages/codex-goalctl && PYTHONPATH=src python3 -m unittest discover -s tests -v)
(cd packages/codex-wakectl && PYTHONPATH=src python3 -m unittest discover -s tests -v)
(cd packages/codex-readcov && cargo test)
python3 scripts/sync-skill-references.py --check
```
