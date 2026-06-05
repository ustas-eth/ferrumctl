# codex-readcov

`codex-readcov` shows which files a Codex thread read, based on its transcript.

Use it to inspect a subagent's read coverage, compare reads between two
snapshots, or compose path lists with normal Unix tools. It is not an
operating-system audit log.

## Install

```sh
cargo install --locked --path .
```

## Usage

```sh
codex-readcov top THREAD_ID
codex-readcov snapshot THREAD_ID > before.json
codex-readcov delta before.json
codex-readcov delta before.json PATH --limit 20
codex-readcov delta before.json PATH --paths-only --limit 0
```

Path operands filter the result. Use `--json` for structured output and
`--paths-only` when composing with `sort`, `comm`, or `uniq`.

More detail: [docs/read-coverage.md](docs/read-coverage.md).

## Codex Skill

This package includes an optional Codex skill for transcript read coverage:

```text
plugins/codex-readcov/skills/codex-readcov/SKILL.md
```

Install it from the `ferrumctl` root marketplace:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-readcov@ferrumctl
```

The skill is optional. It explains when to snapshot, how to inspect deltas, and
how to compose read paths with standard tools.
