# streamctl

`streamctl` provides durable append-only streams for coding agents and
host scripts.

Use it when several participants need a small shared exchange with stable
positions and independent read acknowledgements. It does not wake agents,
deliver input, assign work, or replace project files.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/streamctl
```

From this package directory:

```sh
uv tool install .
```

## Examples

Create a stream and append entries:

```sh
STREAM=$(streamctl create --label "design review")
streamctl append "$STREAM" --author "$A" \
  "The idle race is reproducible. I will test transaction scope next."
streamctl append "$STREAM" --author "$B" --reply-to 1 \
  "Retries show the same gap. I will check cancellation while you test scope."
```

Read entries that one participant has not acknowledged:

```sh
streamctl list "$STREAM" --reader "$B" --json
```

When entries are returned, process them in order and acknowledge the non-null
`.lastPosition` from that exact result:

```sh
streamctl ack "$STREAM" --reader "$B" --through LAST_POSITION
```

An empty result has nothing to acknowledge.

`CODEX_THREAD_ID` is the default author for `append` and the default reader for
`list` and `ack`. An explicit `list --after` range does not infer a reader.
Pass identities explicitly in scripts.

Use `--json` for machine-readable records. The default database is
`$XDG_STATE_HOME/streamctl/streams.sqlite3`, or
`~/.local/state/streamctl/streams.sqlite3` when `XDG_STATE_HOME` is not
set. An existing `codex-streamctl` database remains the default until a
`streamctl` database exists. Select another database with `--state`.

See [docs/stream-semantics.md](docs/stream-semantics.md) for ordering,
acknowledgement, identity, and failure semantics.

## Codex Skill

Install the optional skill when a coding agent should know when to use this
command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add streamctl@ferrumctl
```

The skill lives at
`plugins/streamctl/skills/streamctl/SKILL.md`.
