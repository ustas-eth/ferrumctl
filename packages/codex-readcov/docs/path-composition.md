# Path Composition

This reference describes path filtering and Unix set operations around
`codex-readcov` output.

## Path Filters

Path operands filter reported reads. They do not define a coverage universe.

Relative operands are resolved from the rollout cwd. Absolute operands match
absolute paths. Multiple operands are OR filters.

Output paths are shown relative to the rollout cwd when possible; otherwise they
are shown as absolute paths.

## Complete Path Lists

Use `--paths-only --limit 0` when another command will consume paths:

```sh
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
```

`--limit 0` is important for set operations; the default text output is a top-N
summary, not a complete list.

Use `--json` when a program needs counts and metadata instead of plain paths.

## Negative Coverage

Negative coverage is a set operation outside `codex-readcov`: produce the
expected file set, produce the read file set, then subtract.

```sh
find PATH -type f | sort > all.txt
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

This reports files in `PATH` that were not present in the read list for that
window. It should not be described as proof that the agent could not have
observed the file through another channel.

## Multiple Threads

For several workers, keep each read list as ordinary text and combine with
standard tools:

```sh
sort worker-*.read.txt | uniq -c | sort -nr
```

This keeps union, intersection, frequency, and negative coverage outside the
CLI. The primitive provided by `codex-readcov` is counted read paths.
