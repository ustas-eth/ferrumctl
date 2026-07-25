# codex-streamctl

`codex-streamctl` provides durable append-only streams for coding agents and
host scripts.

Use it when several participants need a small shared exchange with stable
positions and independent read acknowledgements. It does not wake agents,
deliver input, assign work, or replace project files.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-streamctl
```

From this package directory:

```sh
uv tool install .
```

## Examples

Create a stream and append entries:

```sh
STREAM=$(codex-streamctl create --label "design review")
codex-streamctl append "$STREAM" --author "$A" \
  "The idle race is reproducible. I will test transaction scope next."
codex-streamctl append "$STREAM" --author "$B" --reply-to 1 \
  "Retries show the same gap. I will check cancellation while you test scope."
```

Read entries that one participant has not acknowledged:

```sh
codex-streamctl list "$STREAM" --reader "$B" --json
```

When entries are returned, process them in order and acknowledge the non-null
`.lastPosition` from that exact result:

```sh
codex-streamctl ack "$STREAM" --reader "$B" --through LAST_POSITION
```

An empty result has nothing to acknowledge.

`CODEX_THREAD_ID` is the default author for `append` and the default reader for
`list` and `ack`. An explicit `list --after` range does not infer a reader.
Pass identities explicitly in scripts.

Use `--json` for machine-readable records. The default database is
`$XDG_STATE_HOME/codex-streamctl/streams.sqlite3`, or
`~/.local/state/codex-streamctl/streams.sqlite3` when `XDG_STATE_HOME` is not
set. Select another database with `--state`.

See [docs/stream-semantics.md](docs/stream-semantics.md) for ordering,
acknowledgement, identity, and failure semantics.

## Codex Skill

Install the optional skill when a coding agent should know when to use this
command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-streamctl@ferrumctl
```

The skill lives at
`plugins/codex-streamctl/skills/codex-streamctl/SKILL.md`.
