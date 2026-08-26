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
changing the source state. The text is included in the cache key.

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
the matching generated artifact after a successful request.

`index THREAD` is a current view, not another stored index. It reads portable
checkpoints in rollout order, uses a summary for the first checkpoint and an
adjacent diff for each later one, and joins those positions with cached text.
The result can be skimmed or piped to tools such as `rg`. `--jobs N` limits
concurrent requests. If one request fails, successful entries remain cached for
the next run. If the rollout gains another portable checkpoint during
generation, the command reports that the view should be rerun.

Standalone injected memory is omitted from `index` because it is not a
generated checkpoint in the thread's sequential compaction history. It remains
available through `list`, `show`, and explicit `summarize` or `diff` selectors.

## Interpretation

Generated text is a lossy model interpretation. It is useful for finding a
likely checkpoint and understanding broad progression, but it is not proof that
a retained fact is present or absent. Use ordinary transcript search when the
needed words are known. Supply the opaque memory to a suitable recipient when
the task requires its retained fidelity rather than a second-hand description.
