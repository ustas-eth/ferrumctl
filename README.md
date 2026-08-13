# ferrumctl

Small Unix-style control tools for Codex agent workflows.

`ferrumctl` is the repository umbrella. It does not install a wrapper command.
Use the tools separately and compose them with the shell:

- `codex-goalctl` reads and changes persisted Codex thread goals.
- `codex-limitctl` reads Codex subscription limits and usage signals.
- `streamctl` provides durable append-only exchanges with per-reader
  acknowledgements.
- `codex-threadctl` discovers threads, inspects ordered activity, sends
  advisory agent notices, and applies immediate control.
- `codex-wakectl` schedules durable thread attention after later conditions.
- `codex-readcov` counts file-read actions from Codex rollout transcripts.

The optional Codex plugins add skills that explain when agents should use each
command. They do not change CLI behavior.

## Install

```sh
git clone https://github.com/ustas-eth/ferrumctl
cd ferrumctl

uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-limitctl
uv tool install ./packages/streamctl
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
codex plugin add streamctl@ferrumctl
codex plugin add codex-threadctl@ferrumctl
codex plugin add codex-wakectl@ferrumctl
codex plugin add codex-readcov@ferrumctl
```

The marketplace manifest is [.agents/plugins/marketplace.json](.agents/plugins/marketplace.json).

## Upgrade

From an existing checkout, update the installed commands:

```sh
git pull
for package in codex-goalctl codex-limitctl streamctl codex-threadctl codex-wakectl; do
  uv tool install --reinstall "./packages/$package"
done
cargo install --locked --force --path ./packages/codex-readcov
```

When upgrading from `codex-streamctl`, remove the old command and plugin after
installing `streamctl`:

```sh
uv tool uninstall codex-streamctl
codex plugin remove codex-streamctl@ferrumctl
```

Refresh the marketplace, then rerun `codex plugin add NAME@ferrumctl` for each
plugin you use:

```sh
codex plugin marketplace upgrade ferrumctl
codex plugin add codex-threadctl@ferrumctl
```

For a persistent app-server at `unix://`, update all commands and plugins from
the checkout without restarting the server:

```sh
uv run scripts/update-local.py --reload-threads
```

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

Share a durable peer checkpoint and announce it without user input:

```sh
STREAM=$(streamctl create --label "review")
POSITION=$(streamctl append "$STREAM" --author "$A" \
  "The retry result rules out parser order. I will test transaction scope next." \
  --json | jq -r .position)
codex-threadctl notify "$B" --from "$A" \
  "Stream $STREAM has a checkpoint through $POSITION; read after your current work step."
```

When the recipient is known to be loaded and idle, start its next turn without
adding another message:

```sh
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
  --to "$MAIN"
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
codex-wakectl add time --after 30m --to "$SELF"
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

More combinations:

- [Worker workflows](docs/worker-workflows.md)
- [Peer workflows](docs/peer-workflows.md)
- [Host automation](docs/host-automation.md)

## Layout

```text
packages/
  codex-goalctl/
  codex-limitctl/
  streamctl/
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
- [docs/worker-workflows.md](docs/worker-workflows.md)
- [docs/peer-workflows.md](docs/peer-workflows.md)
- [docs/host-automation.md](docs/host-automation.md)
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
