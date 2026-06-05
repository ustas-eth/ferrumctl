<!-- Generated from packages/codex-readcov/docs/snapshot-windows.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Snapshot Windows

This reference describes how `snapshot`, `delta`, and `top` define the transcript
range being counted.

## Snapshot Contents

A snapshot is a JSON cursor for the current end of a rollout. It records:

- snapshot format
- thread id when present in `session_meta`
- canonical rollout path
- rollout cwd
- current line count
- current byte offset

The byte offset is the cursor used by `delta`; the line count is informational.

## Delta Windows

`delta FROM` counts events appended after the `FROM` snapshot up to the current
end of the same rollout.

`delta FROM --to TO` counts the byte range between two explicit snapshots. Both
snapshots must use the same snapshot format, rollout path, and cwd. A `FROM`
snapshot later than `TO` is rejected.

Use an explicit `--to` snapshot when the window must stay fixed while the thread
continues writing to the rollout.

## Top Windows

`top` summarizes a full rollout by default. It also accepts 1-based
`--from-line` and `--to-line` bounds for line-based inspection. Line ranges are
inclusive.

When the first argument to `codex-readcov` is not a subcommand or global flag,
the CLI treats it as `top`. This makes `codex-readcov THREAD_ID` equivalent to
`codex-readcov top THREAD_ID`.

## Live Data

For live rollouts, `delta FROM` uses the current end of the rollout at command
execution time. Re-running the same command later may include more events unless
an explicit `--to` snapshot is used.
