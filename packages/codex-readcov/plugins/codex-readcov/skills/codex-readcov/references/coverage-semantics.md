<!-- Generated from packages/codex-readcov/docs/coverage-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coverage Semantics

This reference describes what `codex-readcov` can and cannot count.

## Source Data

`codex-readcov` reads Codex rollout JSONL transcripts. A target may be a Codex
thread id or a direct path to a rollout JSONL file. Thread ids are resolved by
searching saved rollouts under `$CODEX_HOME/sessions`, or `~/.codex/sessions`
when `CODEX_HOME` is unset.

The tool requires `session_meta` in the rollout to provide the transcript cwd.
That cwd is used for path resolution and display.

## What Counts

The scanner looks for recorded `exec_command` function calls. For each command,
it reconstructs the shell invocation from the recorded `cmd`, `workdir`,
`shell`, and `login` fields, then runs that invocation through
`codex-shell-command`.

Only parser results classified as file reads are counted. Counts are read
actions, not unique files; repeated reads of the same path increment the count.
The transcript records the command request, so classification does not prove
that the command succeeded or returned file contents.

## What Does Not Count

`codex-readcov` does not inspect the filesystem, watch processes, scrape command
output, validate command exit status, or prove that a process opened a file
descriptor. It also does not count file exposure from non-shell transcript
events.

Coverage is therefore a count of transcript-recorded read actions, not proof
that file contents entered model context or that every read was observed.

## Live Rollouts

When reading a live rollout, an unterminated partial final JSONL line is ignored.
Malformed complete JSON lines still fail the scan. This avoids treating a
currently-being-written event as corrupt data.

## Version Sensitivity

The result depends on Codex rollout schema and on `codex-shell-command` parser
behavior. Changes in either can change what is counted without changing
`codex-readcov` command syntax.
