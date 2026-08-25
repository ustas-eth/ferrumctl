# Memory Workflows

Memoryctl transfers retained model state. Thread creation, instructions,
lifecycle control, and durable project records remain separate.

## Disposable Consultation

Use a fresh consultant when an established agent needs another thread's
perspective without accepting lasting influence. Give the consultant the
question, let it call `inject --self` with the donor memory, collect its answer,
and discard the thread.

The consultant can also assimilate the requester's memory when the requester's
retained perspective is needed, but a clear current prompt is often enough.
This topology makes the consultation temporary at the workflow level; memoryctl
itself has no removal operation.

## Older-Self Recall And In-Place Assimilation

An established agent can use `inject --self` to revisit an older checkpoint or
accept a donated perspective into its continuing work. It must call the command
during an active turn and state the purpose explicitly. Memoryctl replaces the
donor turn association with current-turn binding.

The retained current instructions and evidence remain the authority. Extract
useful details from the recalled state and check them against the present
situation instead of reviving obsolete tasks or conclusions.

This operation is durable. A later compaction may absorb the recalled material
into the agent's next memory, so save any conclusions that must remain explicit
in ordinary project artifacts.

## Fresh Handoff And Consolidation

A fresh thread can assimilate one or more memory-only states with `--self`.
Their order is model-visible, and a short current instruction can define the
handoff or synthesis task. This is normally preferable to copying retained
message history.

`inject --to TARGET` preserves each donor's source turn association. Use it
when a loaded fresh target needs source-associated state, not as neutral context
for an established agent.

## Recovery With A Full Checkpoint

A full checkpoint includes the donor's retained user, developer, and agent
messages as well as opaque memory. It requires `--to` and is intended for a
fresh recovery target where those messages are part of the needed state.

The transfer still appends after the target's initial context rather than
replacing its history. Treat the result as a seeded recovery thread, not an
exact continuation of the donor.
