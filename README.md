# ferrumctl

Small Unix-style control tools for Codex agent workflows.

`ferrumctl` is the repository umbrella. It does not install a wrapper command.
Use the tools separately and compose them with the shell:

- `codex-goalctl` reads and changes persisted Codex thread goals.
- `codex-limitctl` reads Codex subscription limits and usage signals.
- `codex-streamctl` provides durable append-only exchanges with per-reader
  acknowledgements.
- `codex-threadctl` discovers threads, inspects ordered activity, sends
  advisory agent notices, and applies immediate control.
- `codex-wakectl` schedules durable thread input after later conditions.
- `codex-readcov` counts file-read actions from Codex rollout transcripts.

The optional Codex plugins add skills that explain when agents should use each
command. They do not change CLI behavior.

## Install

```sh
git clone https://github.com/ustas-eth/ferrumctl
cd ferrumctl

uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-limitctl
uv tool install ./packages/codex-streamctl
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
codex plugin add codex-limitctl@ferrumctl
codex plugin add codex-streamctl@ferrumctl
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

Check shared subscription capacity and recent usage:

```sh
codex-limitctl list
codex-limitctl test codex --window 7d --remaining-at-least 20
codex-limitctl usage --since 7d
codex-limitctl activity --since 24h | head
```

Find recent sessions or retained subagent threads:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-threadctl list --limit 10
codex-threadctl list --parent "$SELF" --limit 5
codex-threadctl search "decision text" --limit 10
```

Share a durable peer update, announce it without user input, and wake an idle
recipient:

```sh
STREAM=$(codex-streamctl create --label "review")
POSITION=$(codex-streamctl append "$STREAM" --author "$A" \
  "I reproduced the race; inspect commit abc123." --json | jq -r .position)
codex-threadctl notify "$B" --from "$A" \
  "Stream $STREAM has unread entries through $POSITION."
codex-threadctl wake "$B"
```

Assign durable work, arrange the coordinator's return, then start the worker:

```sh
WORKER=thread-id
MAIN=main-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json
codex-goalctl replace "$WORKER" "Review this package and mark the goal complete."
codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Automated event: Worker goal reached a terminal status. Inspect it."
codex-threadctl start "$WORKER" "From coordinator: A goal was assigned. Call get_goal and proceed."
```

When the coordinator resumes:

```sh
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

Schedule a self-reminder from a loaded Codex session:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl add time --after 30m --to "$SELF" \
  "Self-scheduled reminder: Review progress."
```

Find tracked files not present in a read list, using the snapshot cwd as the
shared path namespace:

```sh
SCOPE=packages
WORKER_CWD=$(jq -r .cwd worker.before.json)
git -C "$WORKER_CWD" ls-files -- "$SCOPE" | sort > all.txt
codex-readcov delta worker.before.json "$SCOPE" \
  --paths-only --limit 0 | sort > read.txt
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
  codex-limitctl/
  codex-streamctl/
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
- [docs/future-directions.md](docs/future-directions.md)

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
uv run scripts/update-local.py
```

`scripts/check.sh` is the normal pre-commit check. `scripts/codex-smoke.sh` is
the local compatibility probe to run after Codex upgrades; it uses a temporary
`CODEX_HOME` and `XDG_STATE_HOME`, starts only its own app-server, and cleans up
after itself. `scripts/update-local.py` reinstalls the commands from this
checkout and refreshes the plugins in an existing app-server without restarting
the server or its sessions. Pass `--reload-threads` when newly enabled plugins
must become available to existing sessions. It reloads user configuration in
every loaded thread. Model-visible skill instructions update when a thread next
rebuilds its context, such as after compaction, rather than on an ordinary turn.
