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
the item, or that the target acted on it.

Injection does not add ordinary user input, wake an idle thread, or bypass the
native parent's lifecycle ownership of a v2 agent. Lifecycle control remains a
separate operation.

`--self` selects the active `CODEX_THREAD_ID`. It requires `--purpose`, clears
each copied memory's donor turn association, and asks Codex to bind the batch
to the current turn. Memoryctl places an attributed perspective boundary
before and after the memory, and a transition boundary between memories. The
closing boundary contains the exact caller purpose and mechanically resolved
memory ids. It also states whether each source thread came from a local rollout
or editable export metadata. The purpose is a field inside structured content,
so its text remains distinguishable from fields supplied by memoryctl.

`--to TARGET` preserves source turn association instead. A purpose supplied
with a memory-only `--to` transfer is delivered in the same closing boundary.
The two modes remain explicit because their memory items have different turn
binding. Full-checkpoint injection requires `--to`, keeps the exact replacement
history unframed, and is intended for a fresh target. Its optional purpose
appears only in the command receipt.

## Persistence And Order

Once recorded, injected items are part of model-visible history and have no
paired remove operation. A later compaction can combine their influence with
the recipient's history into a new opaque memory.

Repeated `--state` arguments are submitted as one batch in command order. The
order is model-visible and may change the result. Memoryctl labels the first
memory, closes one perspective before opening the next, and closes the final
perspective with its source reference. These boundaries improve source
awareness; they do not guarantee that the model keeps a perspective distinct
or that later compaction preserves the boundary. Full-checkpoint injection is
limited to one source because combining retained histories silently would be a
different operation.

Without `--allow-duplicate`, the command refuses both a repeated memory within
the requested batch and memory already present in the target's current
compacted history or appended after its latest compaction. Earlier replaced
checkpoints remain selectable for older-self recall. This is a preflight guard,
not an atomic idempotency guarantee. If submission becomes uncertain, inspect
the target for the reported memory reference before retrying.

## Provenance And Compatibility

An opaque compaction item does not state which thread donated it, why it was
injected, or how much authority it should carry. The surrounding attributed
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
call supplies useful surrounding provenance. External injection should be
limited to a fresh handoff or recovery target. When an established agent should
remain unchanged, use a disposable consultant that performs its own `--self`
injection.

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
