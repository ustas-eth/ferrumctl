---
name: codex-readcov
description: "Use when transcript-recorded file-read actions are needed for a Codex thread or rollout JSONL file: full-history counts, snapshot deltas, path filtering, or path lists for Unix set operations. Do not use for test coverage, file search, content summaries, operating-system auditing, or proof that a command succeeded or every file access reached model context."
---

# Codex Readcov

## Purpose

Use `codex-readcov` to reconstruct file-read actions from a Codex rollout
transcript. It reports transcript evidence, not live process access, command
success, file contents, or complete model-context exposure.

## Choose A Window

- `top` counts recorded reads across the full transcript.
- `snapshot` stores the current transcript cursor and rollout cwd.
- `delta` counts reads after a snapshot or between two snapshots.
- Path operands filter reported reads; they do not define the expected universe.

Prefer a snapshot and delta for a bounded work interval:

```sh
codex-readcov snapshot THREAD_ID > before.json
codex-readcov delta before.json PATH --limit 20
```

Take an end snapshot when the interval must remain fixed:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json PATH --json
```

Use `top` when the complete retained history is deliberately the window:

```sh
codex-readcov top THREAD_ID PATH --limit 20
```

A v2 agent path is not a rollout identifier. If the threadctl skill is
available, resolve the path and pass its thread id to readcov:

```sh
codex-readcov top "$(codex-threadctl resolve /root/reviewer)" PATH --limit 20
```

`CODEX_THREAD_ID` supplies the tree scope. Otherwise pass `--tree THREAD_ID` to
`resolve`.

## Compose Paths

Use `--paths-only --limit 0` to produce a complete selected path list for
`sort`, `comm`, or `uniq`.

Negative coverage requires an explicit expected set in the snapshot's path
namespace:

```sh
SCOPE=PATH
ROLLOUT_CWD=$(jq -r .cwd before.json)
git -C "$ROLLOUT_CWD" ls-files -- "$SCOPE" | sort > all.txt
codex-readcov delta before.json "$SCOPE" \
  --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

Keep union, intersection, and negative coverage in normal Unix tools.

Readcov classifies recorded command structure. When a dynamic command envelope
cannot be resolved reliably, it fails rather than silently reporting incomplete
coverage as zero. Do not present its output as an operating-system audit or
proof that every reported read reached the model.

Use `--json` when another program will parse output.

## References

- Read `references/coverage-semantics.md` for what counts, transcript
  limitations, live rollout behavior, and parser dependencies.
- Read `references/snapshot-windows.md` for full-history, open-ended, and fixed
  windows.
- Read `references/path-composition.md` for filtering, complete path lists,
  negative coverage, and multi-thread set operations.
- Read `references/coordination-principles.md` when composing coverage with
  goals, live control, scheduled wakes, or partial skill availability.
- Read `references/worker-workflows.md` when coverage is part of worker review.
- Read `references/host-automation.md` when snapshots feed a later script or
  external manager.
