---
name: codex-readcov
description: "Use when you need the host codex-readcov command to inspect transcript-recorded file-read actions for a Codex CLI thread or rollout JSONL file: read counts, snapshot/delta windows, path filtering, paths-only output, or Unix composition of read path lists. Do not use for test coverage, file search, summarizing file contents, operating-system audit logs, or proving that commands succeeded or every file access was observed."
---

# Codex Readcov

## Purpose

Use this skill when you need to inspect file-read actions reconstructed from a
Codex thread's rollout transcript.

Assume `codex-readcov` is installed on the host. It reads transcripts; it does
not inspect live process file descriptors, scrape shell output, measure test
coverage, or summarize file contents.

## Model

- A target is a Codex thread id or a rollout JSONL path.
- `top` counts reads across a transcript.
- `snapshot` records the current transcript cursor.
- `delta` counts reads appended after a snapshot, or between two snapshots.
- Path operands filter reported reads; they do not define a coverage universe.
- Counts classify recorded commands; they do not verify command success or file
  contents returned to the model.
- Current `exec` wrapper calls are parsed as JavaScript. If nested command
  arguments are constructed dynamically, readcov fails instead of returning
  incomplete coverage as zero.

For the current thread, use `CODEX_THREAD_ID` when it is available:

```sh
THREAD=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
```

## Patterns

Snapshot before a work interval:

```sh
codex-readcov snapshot THREAD_ID > before.json
```

Inspect reads appended since that snapshot:

```sh
codex-readcov delta before.json
```

Scope the result only when needed:

```sh
codex-readcov delta before.json PATH [PATH...] --limit 20
```

Use an explicit end snapshot when the window must be fixed:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json PATH --json
```

Use `top` only when the full transcript summary is more useful than a time
window:

```sh
codex-readcov top THREAD_ID PATH --limit 20
```

Produce path lists for Unix set operations:

```sh
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
```

For negative coverage, build the expected set in the snapshot cwd so both
inputs use the same path namespace:

```sh
SCOPE=PATH
ROLLOUT_CWD=$(jq -r .cwd before.json)
git -C "$ROLLOUT_CWD" ls-files -- "$SCOPE" | sort > all.txt
codex-readcov delta before.json "$SCOPE" \
  --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

## References

- Read `references/coverage-semantics.md` when what counts, transcript
  limitations, live rollout behavior, or parser dependency matters.
- Read `references/snapshot-windows.md` when choosing between `top`,
  `snapshot`, `delta`, explicit `--to`, or line ranges.
- Read `references/path-composition.md` when path filtering, `--paths-only`,
  JSON output, negative coverage, or multi-thread set operations matter.
- Read `references/coordination-principles.md` when deciding how read coverage
  composes with persisted goals, live wakes, native controls, or partial skill
  availability.
- Read `references/coordination-recipes.md` for command combinations involving
  coverage audits, worker review, negative coverage, or external managers.
- Read `references/operational-caveats.md` when reliability limits, live
  rollouts, or cross-surface consistency matter.

## Conventions

- Prefer `snapshot` plus `delta` for a work interval.
- Take the first snapshot before the work interval starts.
- Use `top` only when a full-transcript summary is more useful than a time
  window.
- Use path operands for an intentionally scoped view, not as proof that other
  paths were unread.
- Use `--paths-only --limit 0` before `sort`, `comm`, or `uniq`.
- Generate negative-coverage inputs in the snapshot cwd and choose the expected
  universe explicitly. Do not compare rollout-relative output with an
  unrestricted walk of the caller's filesystem.
- Keep negative coverage, union, and intersection outside `codex-readcov`.
- Use `--json` when another program will parse output.
- Do not present results as verified command success, model context exposure,
  OS-level audit data, or proof of every file access.
