---
name: codex-readcov
description: Use when acting as a Codex orchestrator or coding agent that needs transcript read coverage for Codex CLI threads or subagents with the host codex-readcov command. Covers when to snapshot, how to inspect deltas, how to filter by path operands, and how to compose paths-only output with Unix tools. Do not use as an operating-system audit tool.
---

# Codex Readcov

## Purpose

Use this skill when the current Codex session needs to inspect which files
another Codex thread or subagent read according to its transcript.

Assume `codex-readcov` is installed on the host. Treat results as transcript
coverage, not as proof of every file descriptor opened by a process.

## Workflow

Snapshot before a fresh work interval:

```sh
codex-readcov snapshot THREAD_ID > before.json
```

After the worker runs, inspect reads appended since the snapshot:

```sh
codex-readcov delta before.json
```

Scope the result only when needed:

```sh
codex-readcov delta before.json PATH [PATH...] --limit 20
```

Use an explicit end snapshot for a bounded window:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json PATH --json
```

Use `top` only when the full transcript summary is more useful than a time
window:

```sh
codex-readcov top THREAD_ID PATH --limit 20
```

## References

- Read `references/read-coverage.md` when path filtering, JSON output, negative
  coverage, or transcript limitations matter.
- Read `references/orchestrator-worker-loop.md` when using read coverage as part
  of a larger worker-supervision loop.

## Rules

- Prefer `snapshot` plus `delta` for subagent supervision.
- Take the first snapshot before the work interval starts.
- Use path operands only for an intentionally scoped view.
- Use `--paths-only --limit 0` before `sort`, `comm`, or `uniq`.
- Keep set operations outside `codex-readcov`.
- Do not present results as OS-level audit data.
