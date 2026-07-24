<!-- Generated from packages/codex-readcov/docs/path-composition.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

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
expected file set, produce the read file set, then subtract. The expected set
must use the same namespace as readcov output, which is relative to the rollout
cwd when possible.

For a tracked-file audit:

```sh
SCOPE=PATH
ROLLOUT_CWD=$(jq -r .cwd before.json)
git -C "$ROLLOUT_CWD" ls-files -- "$SCOPE" | sort > all.txt
codex-readcov delta before.json "$SCOPE" \
  --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

This reports tracked files in `SCOPE` that were not present in the read list for
that window. The example assumes `SCOPE` is relative to and beneath the rollout
cwd. For an external absolute scope, generate absolute expected paths to match
readcov output. A different audit can deliberately choose another expected
universe, but unrestricted filesystem walks commonly include ignored build
outputs, environments, and caches. The result should not be described as proof
that the agent could not have observed a file through another channel.

## Multiple Threads

For several workers, keep each read list as ordinary text and combine with
standard tools:

```sh
sort worker-*.read.txt | uniq -c | sort -nr
```

This keeps union, intersection, frequency, and negative coverage outside the
CLI. The primitive provided by `codex-readcov` is counted read paths.
