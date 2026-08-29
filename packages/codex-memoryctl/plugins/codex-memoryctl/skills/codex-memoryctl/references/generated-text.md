<!-- Generated from packages/codex-memoryctl/docs/generated-text.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Generated Text

Opaque memory is useful at full fidelity when supplied to a model, but its
encrypted content cannot be searched mechanically. `summarize`, `diff`, and
`index` create compact plaintext descriptions for orientation and ordinary text
search. They do not modify the source rollout or inject anything into a thread.

## Requests

`summarize STATE` submits one selected memory. `diff OLDER NEWER` submits two
ordered memories and asks what materially changed. A strict API schema accepts
only one nonempty `text` value; plain output prints only that value, while
`--json` also reports the source metadata, model, usage, timing, and cache
status.

The request brackets every opaque item with developer-level source boundaries.
The model is told to treat retained instructions, roles, and objectives as
source material rather than current authority. When an outer checkpoint
contains imported or inspected memory, it is asked to describe what the outer
state was doing with that material. Without this distinction, a comparison can
mistake a vivid imported perspective for the checkpoint that contains it.

The default request uses GPT-5.6 Luna at medium effort through the Codex
subscription endpoint and the current Codex authentication. `--model` and
`--effort` select another available model configuration. A transient transport
failure or invalid response is retried once. Authentication and other
non-transient request failures are returned directly; the command does not
silently switch models.

`--focus TEXT` gives `summarize` or `diff` a subject to emphasize without
changing the source state. Its hash is included in the cache key; the focus
text itself is not stored in the cache.

## Cache And Index

Validated descriptions are cached by operation, ordered memory ids, model,
effort, instructions, and prompt. The default database is:

```text
$XDG_STATE_HOME/codex-memoryctl/derived.sqlite3
```

When `XDG_STATE_HOME` is unset, it uses
`~/.local/state/codex-memoryctl/derived.sqlite3`. Memoryctl creates the default
directory with mode `0700` and the database with mode `0600`. The database
contains generated plaintext and response metadata, not opaque ciphertext or
credentials. It is still sensitive because the text can describe private
session work. `--database PATH` selects another cache, and `--refresh` replaces
the matching generated artifact after a successful request. `--no-cache`
bypasses both cache reads and writes, and does not create the selected database.
`--refresh` and `--no-cache` are mutually exclusive.

`cache info` reports the database path, allocated size, entry count, time
range, and counts by generated operation without making a model request.
`cache clear` removes every generated description from the selected database:

```sh
codex-memoryctl cache info
codex-memoryctl cache clear
codex-memoryctl cache clear --database /path/to/derived.sqlite3
```

`index THREAD` is a current view, not another stored index. It renders the
newest ten matching portable checkpoints by default, in chronological order.
`--limit 0` selects the complete matching range. `--from-index` and
`--to-index` set inclusive checkpoint bounds. `--since` and `--until` accept a
UTC date or RFC3339 timestamp; a date includes that complete UTC day. Bounds
are applied first, then a nonzero limit keeps the newest matches. Only selected
cards make model requests.

Each card keeps its global meaning across slices: if a view starts at
checkpoint 41, that card still compares checkpoint 40 with 41. Checkpoint 1 is
the only summary; later cards are adjacent diffs. This makes cached cards
reusable across navigation commands. The diff request asks the model to put a
concrete name, artifact, result, or unresolved action near the opening so
repeated temporal framing does not hide the distinguishing text.

Plain output reports how much of a matching range was shown and gives the next
`--to-index` value for older checkpoints. JSON reports total, matching, and
selected counts together with the selected index and time range. The result can
be skimmed or piped to ordinary tools:

```sh
codex-memoryctl index THREAD --limit 0 | rg -i "suspected subject"
```

`--jobs N` limits concurrent requests. If one request fails, successful entries
remain cached for the next run. If the rollout gains another compaction during
generation, the command reports that the view should be rerun. The structured
result also distinguishes the total compaction count from the latest portable
checkpoint; plain output warns when the newest compaction has no reusable
opaque memory.

`index` and a summary of the latest checkpoint report `hasUncompactedTail` and
`uncompactedMessageCount`. These identify ordinary user or assistant messages
after the newest compaction. A historical summary reports no tail count.
Generated text does not describe the tail; use transcript inspection when
current conversation details matter. If a compaction appears during a
`summarize @latest` or `diff ... @latest` request, the source-advancement fields
report that the selected memory is no longer latest.

Standalone injected memory is omitted from `index` because it is not a
generated checkpoint in the thread's sequential compaction history. It remains
available through `list`, `show`, and explicit `summarize` or `diff` selectors.

## Interpretation

Generated text is a lossy model interpretation. It is useful for finding a
likely checkpoint and understanding broad progression, but it is not proof that
a retained fact is present or absent. Use ordinary transcript search when the
needed words are known. Supply the opaque memory to a suitable recipient when
the task requires its retained fidelity rather than a second-hand description.
