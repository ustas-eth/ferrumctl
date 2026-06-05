# codex-readcov

`codex-readcov` reports which files a Codex thread read according to its
transcript.

Use it to inspect worker read coverage, compare reads between snapshots, find
missed files, or compose path lists with normal Unix tools. It is not an
operating-system audit log.

## Install

From the `ferrumctl` root:

```sh
cargo install --locked --path ./packages/codex-readcov
```

From this package directory:

```sh
cargo install --locked --path .
```

## Examples

Show the top read files for a thread:

```sh
codex-readcov top THREAD_ID
```

Snapshot before work, then inspect what was read afterward:

```sh
codex-readcov snapshot THREAD_ID > before.json
codex-readcov delta before.json PATH --limit 20
```

Produce a complete read path list for Unix set operations:

```sh
codex-readcov delta before.json PATH --paths-only --limit 0
```

Find expected files that were not present in the read list:

```sh
find PATH -type f | sort > all.txt
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

Path operands filter the result. Use `--json` for structured output and
`--paths-only` when composing with `sort`, `comm`, or `uniq`.

More detail:

- [docs/coverage-semantics.md](docs/coverage-semantics.md)
- [docs/snapshot-windows.md](docs/snapshot-windows.md)
- [docs/path-composition.md](docs/path-composition.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-readcov@ferrumctl
```

The skill lives at `plugins/codex-readcov/skills/codex-readcov/SKILL.md`.
