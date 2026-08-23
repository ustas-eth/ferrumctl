<!-- Generated from packages/codex-memoryctl/docs/memory-model.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Memory Model

`codex-memoryctl` reads Codex rollout JSONL files. It does not decrypt or
summarize their contents.

## Checkpoints And Memory

A `compacted` rollout record replaces the model-visible history used when the
thread continues. Its `replacement_history` normally contains:

- retained user messages;
- selected developer and agent messages retained by Codex;
- one opaque Responses API `compaction` item.

The command calls the full record a **checkpoint** and the opaque item its
**memory**. A memory-only transfer preserves the target's surrounding history.
A full-checkpoint transfer appends the source's retained context as well.

Older or non-OpenAI compactions may have no portable opaque item. They are not
reported as injectable memory.

## Observations

`list` reports two origins:

- `checkpoint` identifies memory found in a generated compaction checkpoint;
- `standalone` identifies a compaction item persisted separately, normally by
  an earlier injection.

A SHA-256 digest of `encrypted_content` identifies the opaque memory. Matching
digests show that the same encrypted object appears in more than one place;
they do not show that a model read or adopted it.

Checkpoint selectors are local to one rollout:

- `latest` selects the newest generated checkpoint, or the newest standalone
  memory when the rollout has no generated checkpoint;
- `window:N` uses Codex's compaction window number;
- `index:N` uses the 1-based order of all `compacted` records in the rollout;
- `sha256:PREFIX` selects an unambiguous memory digest in that rollout.

Window metadata is absent from some older rollouts. The checkpoint index and
digest remain available when the record contains portable memory.

## Sources And Freshness

Thread ids are resolved under `$CODEX_HOME/sessions` and
`$CODEX_HOME/archived_sessions`. A direct rollout path is also accepted. Both
v1 and v2 agents use ordinary thread ids and separate rollout paths.

Canonical task names such as `/root/reviewer` require the selected app-server
and normal tree-scoped resolution. Resolve and retain the thread id when a
reference must remain attached to the same conversation.

Active rollouts can grow while they are read. A partial final JSONL record is
ignored; malformed complete records fail instead of being silently skipped.
