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
to the current turn. The same batch ends with an attributed `memoryctl` item
containing the exact purpose and canonical source memory references. This
places the caller's intent after the opaque memories without turning it into
user or developer instruction.

`--to TARGET` preserves source turn association instead. A purpose supplied
with `--to` appears only in the command receipt. The two modes are explicit
because they give the injected memory different framing. Full-checkpoint
injection requires `--to` and is intended for a fresh target.

## Persistence And Order

Once recorded, injected items are part of model-visible history and have no
paired remove operation. A later compaction can combine their influence with
the recipient's history into a new opaque memory.

Repeated `--state` arguments are submitted as one batch in command order. The
order is model-visible and may change the result. Full-checkpoint injection is
limited to one source because combining retained histories silently would be a
different operation.

The command refuses memory already present in the target's current compacted
history or appended after its latest compaction unless `--allow-duplicate` is
present. Earlier replaced checkpoints remain selectable for older-self recall.
This is a preflight guard, not an atomic idempotency guarantee. If submission
becomes uncertain, inspect the target for the reported memory reference before
retrying.

## Provenance And Compatibility

An opaque compaction item does not state which thread donated it, why it was
injected, or how much authority it should carry. The attributed item added by
`--self` supplies that missing local context. It reports caller intent and
source references; it does not decode, summarize, or assign authority to the
memory.

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
changing that limitation.

Memory-only exports contain encrypted content and source metadata.
Full-checkpoint exports additionally contain retained plaintext conversation
items. Both should be handled as sensitive session material.
