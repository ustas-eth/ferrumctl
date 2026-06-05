---
name: codex-readcov
description: Use when acting as a Codex orchestrator or coding agent that needs transcript read coverage for Codex CLI threads or subagents with the host codex-readcov command. Covers when to snapshot, how to inspect deltas, how to filter by path operands, and how to compose paths-only output with Unix tools. Do not use as an operating-system audit tool.
---

# Codex Readcov

## Purpose

Use this skill when the current Codex session needs to inspect transcript read
coverage for another Codex thread or subagent.

`codex-readcov` counts file read actions classified by Codex's own command
parser from recorded `exec_command` calls. Treat it as transcript coverage, not
as proof of every file descriptor opened by the process.

Assume `codex-readcov` is installed on the host.

## Orchestrator Workflow

1. Identify the target thread id. For Codex subagents, use the subagent
   `agent_id` / thread id returned by the spawn operation.

2. For a fresh work interval, snapshot after the thread exists and before the
   worker is woken or assigned substantial work:

```sh
codex-readcov snapshot THREAD_ID > before.json
```

3. After the worker runs, inspect reads appended since the snapshot:

```sh
codex-readcov delta before.json
```

4. Scope the result only when needed by passing path operands:

```sh
codex-readcov delta before.json PATH [PATH...] --limit 20
```

5. Use an explicit end snapshot for a bounded window:

```sh
codex-readcov snapshot THREAD_ID > after.json
codex-readcov delta before.json --to after.json PATH --json
```

Use `top` only when the full transcript summary is more useful than a time
window:

```sh
codex-readcov top THREAD_ID PATH --limit 20
```

## Output Choices

Default output is a ranked count table. Use JSON when a program needs counts and
snapshot metadata:

```sh
codex-readcov delta before.json PATH --json
```

Use paths-only output for Unix set operations:

```sh
codex-readcov delta before.json PATH --paths-only --limit 0
```

No path operands means all resolved read paths. Relative operands are resolved
from the rollout cwd; absolute operands match absolute paths.

## Composition

Keep set operations outside `codex-readcov`.

Negative coverage requires an explicit file universe:

```sh
(cd PATH && git ls-files | sed 's#^#PATH/#') | sort > expected.txt
codex-readcov delta before.json PATH --paths-only --limit 0 | sort > read.txt
comm -23 expected.txt read.txt
```

For multiple subagents, save one read list per worker and aggregate with normal
Unix tools:

```sh
sort agent-*.read.txt | uniq -c | sort -nr
```

## Rules

- Prefer `snapshot` plus `delta` for subagent supervision.
- Take the first snapshot before the work interval starts; otherwise the delta
  cannot show what happened before that point.
- Use path operands only for an intentionally scoped view.
- Use `--paths-only --limit 0` before `sort`, `comm`, or `uniq`.
- Do not add built-in negative coverage or union/intersection logic; compose
  those from path lists.
- Do not present results as OS-level audit data.

## Quick Reference

```sh
codex-readcov top THREAD_ID [PATH...] [--limit N|--limit 0] [--json|--paths-only]
codex-readcov snapshot THREAD_ID > before.json
codex-readcov delta before.json [PATH...] [--to after.json] [--limit N|--limit 0] [--json|--paths-only]
```
