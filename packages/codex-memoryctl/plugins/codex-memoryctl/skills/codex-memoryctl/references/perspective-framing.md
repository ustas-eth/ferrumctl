<!-- Generated from packages/codex-memoryctl/docs/perspective-framing.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Perspective Framing

Opaque memory can influence a response without remaining recognizable as a
separately sourced perspective. Four outcomes should be distinguished:

- **semantic access**: retained content contributes to reasoning;
- **source awareness**: the model attributes that content to the imported
  memory;
- **assimilation**: the imported state participates as the model's own
  continuity;
- **workflow isolation**: the original agent remains unchanged because another
  thread performs the consultation.

None of these outcomes proves another. A fluent answer may have poor source
awareness, while a model asked to inspect an opaque object may report it
unavailable even though the same state works as retained context.

## State The Relationship

Choose whether the operation is recall or consultation. Recall deliberately
assimilates an older self. Consultation treats imported state as an attributed
perspective for the current question.

For consultation, state the relationship positively:

```text
Use the preceding retained state as an attributed perspective for the current
question. Keep the current instructions and evidence authoritative.
```

Avoid asking the model to prove that it can inspect or decode an opaque object.
The item is presented as retained conversation state, not as a plaintext
document addressed by memoryctl's `m:` reference. Also avoid relying on a
negative identity instruction to create separation; rejecting the imported
identity can suppress useful access along with assimilation.

`inject --self` provides useful surrounding context when an agent calls it in
its own active turn: the call establishes intent before the imported state,
and memoryctl brackets the state with attributed source context and places the
exact purpose afterward. Memory-only `inject --to` uses the same boundaries
while preserving the source turn association. This improves framing but does
not guarantee source awareness. Full-checkpoint transfer remains unframed
because it copies an exact retained history into a fresh handoff or recovery
target.

## Bound A Perspective

Memoryctl brackets one imported memory like this:

```text
opening provenance: the next retained state is perspective A
opaque memory A
closing provenance: perspective A ends; answer the current question from it
```

The opening item establishes the source label. The closing item binds that
label to the preceding opaque state and, when supplied, carries the caller's
purpose. Both are attributed `memoryctl` items with structured fields, so a
multiline purpose cannot visually imitate a resolved source field.

For several opaque memories, close one perspective before opening the next:

```text
open A
opaque memory A
close A; open B
opaque memory B
close B
current comparison or synthesis request
```

Repeated `--state` arguments create these transition boundaries in command
order. They make the provenance legible; they cannot force the model to retain
source separation. Use separate disposable consultants when stronger workflow
isolation is needed.

## Compare Incrementally

A caller that assembles raw API input for a search index often needs the new
state at full fidelity but only a compact anchor for the preceding state. It
can avoid two competing opaque perspectives:

```text
opaque memory B
provenance: the preceding retained state is B
current request containing a validated plaintext card for A
```

This arrangement preserves opaque access to B and gives A an explicit source
boundary. It is cheaper than supplying two opaque states, but the comparison
inherits any omission or mistake in A's text card.

## Keep Locators Mechanical

Thread ids, memory references, checkpoint positions, timestamps, and source
labels already belong to the caller. Attach them to a generated description
after the model responds instead of asking the model to reproduce them. If a
schema must include them, validate exact equality and reject a mismatch. A
semantically correct description can still alter an identifier fluently.

## Preserve Attribution

Framing affects the current model request; it does not rewrite the opaque item.
A later compaction can assimilate imported influence into a new memory and lose
the perceived boundary. Record conclusions that need durable attribution in an
ordinary artifact together with their source references. Use a disposable
consultant when the established thread itself must remain unchanged.
