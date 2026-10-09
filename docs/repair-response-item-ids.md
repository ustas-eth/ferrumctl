# Repair Legacy Response Item IDs

Older ferrumctl versions authored some agent-message IDs that Codex's Responses
backend cannot reuse. Affected threads can fail intermittently with:

```text
Supplied input item IDs require persisted-item lookup that is not supported by rustponsesapi.
```

The corrected generators prevent new occurrences. Updating commands alone does
not repair IDs already retained in a thread or its compaction checkpoints.

From an updated ferrumctl checkout, inspect local sessions first:

```sh
python3 scripts/repair-response-item-ids.py
```

Close affected sessions and stop their app servers before applying the repair:

```sh
python3 scripts/repair-response-item-ids.py --apply \
  --backup-dir /path/to/new-private-backup-directory
```

Use `--thread THREAD_ID` to limit the operation, or `--codex-home PATH` for
another installation. The backup directory must be new; originals and a JSON
manifest are preserved there. Resume the threads afterward.

The Linux helper clears only the legacy `amsg_memoryctl_<32 hex>` and
`amsg_<32 hex>` IDs on agent-message objects. JSON whitespace replaces the
removed ID bytes, preserving every line length, ordinal, and decoded byte
offset used by paginated history and shared prefixes. Message text, provenance,
provider-issued IDs, opaque memory, and thread IDs remain unchanged. SQLite
history indexes require no rebuild because their positions do not move.

Files with live Codex writers are reported as `busy` and left untouched. Loaded
threads must still be resumed after repair to discard old in-memory context.
Compressed `.jsonl.zst` files are reported, not edited. Errors, busy files, and
uninspected compressed files produce a nonzero exit status; check the report
before assuming the whole selection is repaired.
