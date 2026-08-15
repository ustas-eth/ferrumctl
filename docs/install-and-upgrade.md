# Install And Upgrade

This guide covers command installation, optional Codex skills, shared
app-server setup, and updates from an existing checkout.

## Install Commands

Clone the repository:

```sh
git clone https://github.com/ustas-eth/ferrumctl
cd ferrumctl
```

Install one or more Python commands with `uv`:

```sh
uv tool install ./packages/codex-goalctl
uv tool install ./packages/codex-limitctl
uv tool install ./packages/streamctl
uv tool install ./packages/codex-threadctl
uv tool install ./packages/codex-wakectl
```

Install `codex-readcov` with Cargo:

```sh
cargo install --locked --path ./packages/codex-readcov
```

Each package can be installed independently.

## Install Codex Skills

Add the repository marketplace once, then install the skills for the commands
you use:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-goalctl@ferrumctl
codex plugin add codex-limitctl@ferrumctl
codex plugin add streamctl@ferrumctl
codex plugin add codex-threadctl@ferrumctl
codex plugin add codex-wakectl@ferrumctl
codex plugin add codex-readcov@ferrumctl
```

If a shared app-server was already running, restart it after the first plugin
install or use the repository update helper below to refresh its plugin cache.
Existing sessions rebuild their model-visible skill list after a context
refresh such as compaction.

## Shared App Server

`codex-threadctl` live control and `codex-wakectl` delivery require the target
sessions to be loaded on the same app-server endpoint:

```sh
codex app-server --listen unix://
codex --remote unix://
codex-threadctl loaded
```

Keep the app-server process running while those sessions need live control.
`codex-goalctl` and `codex-limitctl` use short-lived app-server processes.
`codex-readcov` and `streamctl` use local files. Their normal operation is
independent of the shared server.

The `codex-wakectl` systemd timer checks the default queue at a fixed interval:

```sh
codex-wakectl systemd install --interval 30s
```

See [codex-wakectl runtime semantics](../packages/codex-wakectl/docs/runtime-semantics.md)
for custom state files, runner behavior, and delivery limits.

## Upgrade

Update the checkout and reinstall the commands you use:

```sh
git pull

for package in codex-goalctl codex-limitctl streamctl codex-threadctl codex-wakectl; do
  uv tool install --reinstall "./packages/$package"
done
cargo install --locked --force --path ./packages/codex-readcov
```

Refresh the marketplace and reinstall each plugin you use:

```sh
codex plugin marketplace upgrade ferrumctl
codex plugin add codex-threadctl@ferrumctl
```

Repeat the second command for the other installed ferrumctl plugins.

For a persistent app-server at `unix://`, the repository helper can reinstall
all commands and refresh all plugins while the server keeps running:

```sh
uv run scripts/update-local.py
```

Use `--reload-threads` when newly enabled plugins must become available to
existing loaded sessions. Model-visible skill instructions still update when a
thread next rebuilds its context.

## Check A Codex Upgrade

Ferrumctl depends on Codex app-server methods and local rollout formats. After
upgrading Codex, run the isolated compatibility check before relying on the
tools in long-running work:

```sh
scripts/codex-smoke.sh
```

The check uses temporary Codex and state directories, starts its own
app-server, and removes its temporary data when finished.

## Migrate From codex-streamctl

`streamctl` replaced the earlier `codex-streamctl` package name. After
installing `streamctl`, remove the old command and plugin:

```sh
uv tool uninstall codex-streamctl
codex plugin remove codex-streamctl@ferrumctl
```
