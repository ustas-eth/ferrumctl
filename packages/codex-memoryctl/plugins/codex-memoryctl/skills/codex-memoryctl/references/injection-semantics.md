<!-- Generated from packages/codex-memoryctl/docs/injection-semantics.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Injection Semantics

`inject` sends an ordered item batch through Codex app-server
`thread/inject_items`. The target must be loaded on that server.

Codex handles the accepted batch according to live turn state:

- during an active turn, the items enter pending model input and may not appear
  in the rollout until Codex processes them;
- while idle, the items are recorded immediately for a later turn.

The state can change during submission, and the app-server response does not
identify which case occurred. `accepted` therefore means only that the server
accepted the request. It does not mean that a turn started, that the model read
the item, or that the target acted on it. `targetStatusBefore` reports the live
status observed before submission, not a post-injection confirmation.

Injection does not add ordinary user input or wake an idle thread. Current
Codex rejects `thread/inject_items` for parent-owned v2 children, including when
the child invokes memoryctl with `--self`. Task-name resolution and resume do
not transfer that ownership. Use an independent root or disposable consultant
when the workflow requires memory injection.

`--self` is the recipient-owned preset. It selects the active
`CODEX_THREAD_ID`, requires `--purpose`, clears each copied memory's donor turn
association, and submits the batch to the current turn. Memoryctl surrounds
the memory with attributed source boundaries and places the exact purpose in
the closing boundary.

`--to TARGET` exposes external transfer to a loaded target that accepts direct
app-server injection. Memory-only transfer preserves the source turn
association and uses the same boundaries by default. These defaults can be
selected explicitly or changed independently:

```sh
codex-memoryctl inject --to TARGET --state SOURCE@latest \
  --binding source --framing boundaries
codex-memoryctl inject --to TARGET --state SOURCE@latest \
  --binding current --framing none
```

`--binding current` requires an active target turn and accepts memory only.
`--framing none` appends the memory item without source boundaries; it cannot
carry `--purpose`. The source references and chosen mechanics remain present in
the command receipt.

`--expect-no-turns` is an optional preflight for callers that require no
materialized target turn yet. It does not assert that the history contains no
previously injected items. The check and injection are separate app-server
requests, so the result is not an atomic freshness guarantee.

A full checkpoint requires `--to`, source binding, and no perspective framing.
It appends the source's exact replacement history and does not accept a purpose;
the target's ordinary instruction supplies its current task.

## Persistence And Order

Once recorded, injected items are part of model-visible history and have no
paired remove operation. A later compaction can combine their influence with
the recipient's history into a new opaque memory.

Repeated `--state` arguments are submitted as one batch in command order. The
order is model-visible and may change the result. With boundary framing,
memoryctl labels the first memory, closes one perspective before opening the
next, and closes the final perspective with its source reference. The
boundaries improve source awareness but cannot keep perspectives separate by
force. With framing disabled, the opaque items remain adjacent and carry no
model-visible memoryctl source labels. Full-checkpoint injection is limited to
one source because combining retained histories silently would be a different
operation.

Without `--allow-duplicate`, the command refuses both a repeated memory within
the requested batch and memory already present in the target's current
compacted history or appended after its latest compaction. Earlier replaced
checkpoints remain selectable for older-self recall. This is a preflight guard,
not an atomic idempotency guarantee. If submission becomes uncertain, inspect
the target for the reported memory reference before retrying.

## Provenance And Compatibility

An opaque compaction item does not state which thread donated it, why it was
injected, or how much authority it should carry. When enabled, the surrounding
items supply local source labels and caller intent; they do not decode,
summarize, or assign authority to the memory.

Semantic use and source awareness are separate outcomes. A model may recover
useful content while treating it as its own continuity, or may lose track of
which of several memories supplied a detail. The perspective boundaries
improve surrounding provenance but are not an isolation guarantee. See
[Perspective framing](perspective-framing.md) when the imported state should
remain an attributed foreign perspective.

Turn association is delivery metadata, not provenance. Current-turn binding
does not identify the donor, make the encrypted state a neutral document, or
guarantee that the recipient retains its role and objective. Donor content and
order can still redirect the recipient.

When an established thread requests and performs its own injection, its tool
call supplies useful surrounding provenance. External injection into an
established target remains a legitimate low-level operation, but it is a
durable transplantation rather than neutral reference material. Use a
disposable consultant when the original thread should remain unchanged.

Opaque compaction memory is produced by OpenAI. Known non-OpenAI targets are
rejected by default because JSON acceptance does not establish provider
compatibility. `--allow-non-openai` bypasses the compatibility check without
changing that limitation. An OpenAI provider passes this transport check, but
a recipient model may still fail to recover useful content from memory
produced by another model. Validate a cross-model workflow before relying on
it.

Memory-only exports contain encrypted content and source metadata.
Full-checkpoint exports additionally contain retained plaintext conversation
items. The compaction digest is validated when an export is read; its source
thread, time, model, and checkpoint fields are editable claims. Injection
receipts and perspective boundaries identify them as export metadata rather
than local rollout provenance. Both export forms should be handled as sensitive
session material.
