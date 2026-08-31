# Memory Workflows

Memoryctl transfers retained model state. Thread creation, instructions,
lifecycle control, and durable project records remain separate.

## Disposable Consultation

Use a fresh consultant when an established agent needs another thread's
perspective without accepting lasting influence. Give the consultant the
question, let it call `inject --self` with the donor memory, collect its answer,
and discard the thread.

The consultant must accept direct app-server injection. Current Codex
parent-owned v2 children do not; create an independent root consultant when
using this workflow.

The consultant can also assimilate the requester's memory when the requester's
retained perspective is needed, but a clear current prompt is often enough.
This topology makes the consultation temporary at the workflow level; memoryctl
itself has no removal operation.

Temporary workflow scope and model-level perspective separation are different.
The consultant may use donor memory as its own retained continuity while
answering the question. When the answer must preserve which perspective
supplied a claim, use the framing described in [Perspective
framing](perspective-framing.md).

## Older-Self Recall And In-Place Assimilation

An established agent that accepts direct app-server injection can use
`inject --self` to revisit an older checkpoint or accept a donated perspective
into its continuing work. It must call the command during an active turn and
state the purpose explicitly. Memoryctl replaces the donor turn association
with current-turn binding, brackets each memory with its source reference, and
records that exact purpose in the closing boundary. The purpose should say how
the retained perspective relates to the current question; it does not need to
restate the current role.

The retained current instructions and evidence remain the authority. Extract
useful details from the recalled state and check them against the present
situation instead of reviving obsolete tasks or conclusions.

This operation is durable. A later compaction may absorb the recalled material
into the agent's next memory, so save any conclusions that must remain explicit
in ordinary project artifacts.

The same mode works when another controller finds the memory first. Give the
established recipient the memory reference and the concrete question, then let
the recipient run `inject --self` during its own turn. This keeps the request,
injection, and purpose together without requiring the controller to alter the
thread externally.

## Fresh Handoff And Consolidation

A fresh thread can assimilate one or more memory-only states with `--self`.
Their order is model-visible, and a short current instruction can define the
handoff or synthesis task. Memoryctl places a source boundary around each
state. This is normally preferable to copying retained message history.

An ordered batch is not a set of isolated channels. The boundaries improve
attribution but cannot guarantee it. When donors must remain independently
isolated, consult them in separate threads.

An external controller can use `inject --to TARGET` when the target accepts
direct app-server injection. The memory-only defaults preserve each donor's
source turn association and add source boundaries. Use `--expect-no-turns` when
an automation depends on the target having no materialized turns; the command
otherwise permits established targets.

External injection into an established thread is durable transplantation. It
can be useful for controlled consolidation, recovery, and low-level studies,
but it cannot promise the effect of neutral reference material. The controller
can select `--binding source|current` and `--framing boundaries|none` when those
mechanics matter. Current binding requires an active target turn. Unframed
transfer adds no model-visible source labels.

## Recovery With A Full Checkpoint

A full checkpoint includes the donor's retained user, developer, and agent
messages as well as opaque memory. It requires `--to` and is intended for a
fresh recovery target where those messages are part of the needed state.
`--expect-no-turns` can check that assumption before submission.

The transfer still appends after the target's initial context rather than
replacing its history. Treat the result as a seeded recovery thread, not an
exact continuation of the donor.
