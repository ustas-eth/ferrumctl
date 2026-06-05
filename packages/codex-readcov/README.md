# codex-readcov

Count file read actions in Codex rollout transcripts.

`codex-readcov` reads Codex rollout JSONL, finds recorded `exec_command` calls,
runs them through Codex's own command parser, and counts parser results with
`type = "read"`. It does not scrape shell output or inspect the filesystem.

## Install

```sh
cargo install --locked --path .
```

The Codex skill and local plugin live under `plugins/codex-readcov/`.

## Usage

Count all reads:

```sh
codex-readcov top THREAD_ID
codex-readcov top ~/.codex/sessions/.../rollout-THREAD_ID.jsonl
```

Limit to paths by passing path operands:

```sh
codex-readcov top THREAD_ID PATH [PATH...]
```

Relative path operands are resolved from the rollout cwd. Absolute operands are
matched as absolute paths. Multiple operands are OR filters. Output paths are
shown relative to the rollout cwd when possible, otherwise absolute.

For compatibility, `codex-readcov THREAD_ID ...` is treated as
`codex-readcov top THREAD_ID ...`.

## Deltas

Create a snapshot before a subagent starts work:

```sh
codex-readcov snapshot THREAD_ID > before.json
```

Later, count reads appended after that snapshot:

```sh
codex-readcov delta before.json
codex-readcov delta before.json PATH
```

Compare two explicit snapshots:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json PATH --json
```

`delta` accepts `-` for the first snapshot:

```sh
codex-readcov snapshot THREAD_ID | codex-readcov delta -
```

Snapshots are JSON cursors with the rollout path, rollout cwd, JSONL line, and
byte offset.

## Output

Default output is a table:

```text
    8  src/example/a.rs
    7  src/example/b.rs
```

Use `--json` for structured output, `--paths-only` for one path per line,
`--limit 0` for all rows, and `--verbose` for diagnostics on stderr.

Example negative coverage with standard tools:

```sh
find PATH -type f | sort > all.txt
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

## Scope

This is transcript coverage, not an operating-system audit log. It reports what
Codex's command parser classifies as file reads from recorded shell tool calls.
When reading a live rollout, an unterminated partial final JSONL line is ignored.
