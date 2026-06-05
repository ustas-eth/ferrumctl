# Read Coverage

`codex-readcov` reports which files a Codex thread read, based on its rollout
transcript. It is transcript coverage, not an operating-system audit log.

## What Counts

The tool reads rollout JSONL, finds recorded shell tool calls, runs the command
arguments through Codex's command parser, and counts parser results classified
as file reads.

It does not scrape shell output and does not inspect the filesystem to prove
that a process opened a file descriptor.

When reading a live rollout, an unterminated partial final JSONL line is ignored.

## Common Use

Count reads in a full thread:

```sh
codex-readcov top THREAD_ID
```

Snapshot before a work interval:

```sh
codex-readcov snapshot THREAD_ID > before.json
```

Count reads appended after that snapshot:

```sh
codex-readcov delta before.json
```

Compare two explicit snapshots:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json --json
```

## Path Operands

Path operands filter the result:

```sh
codex-readcov delta before.json PATH [PATH...]
```

Relative operands are resolved from the rollout cwd. Absolute operands match
absolute paths. Multiple operands are OR filters. Output paths are shown
relative to the rollout cwd when possible, otherwise absolute.

## Composition

Use `--paths-only --limit 0` for Unix set operations:

```sh
find PATH -type f | sort > all.txt
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

For multiple workers:

```sh
sort agent-*.read.txt | uniq -c | sort -nr
```

Keep negative coverage, union, and intersection outside `codex-readcov`; the
tool's primitive is counted read paths.
