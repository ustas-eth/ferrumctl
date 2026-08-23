<!-- Generated from packages/codex-memoryctl/docs/memory-workflows.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Memory Workflows

The command exposes state operations. Thread creation, lifecycle control,
instructions, and evaluation remain separate.

## In-Place Consultation

An established agent can request another thread's memory and call `inject`
itself. The default memory-only mode leaves its own retained instructions around
the donated state. The receiving agent should state why it is consulting the
memory before the tool call and judge the result against its current goal.

This is durable assimilation, not a temporary lookup. Continue through at
least one later compaction when the purpose is to study identity or retention.

## Disposable Consultation

Use a fresh thread when the original agent must remain unchanged. Frame the
consultation in that thread, inject the requester and donor memories in the
intended order, collect its answer, and discard the consultation thread.

This topology provides temporary consultation at the workflow level without
requiring a nonexistent history-removal operation.

## Older-Self Recall

Select an earlier checkpoint from the same thread and inject its memory only.
The current retained messages remain in place and can help the agent understand
that it deliberately revisited an older state. Compare behavior before and
after the recipient's next compaction rather than treating the first answer as
proof of stable recall.

## Cloning And Consolidation

Memory-only batches are the safer starting point for a fresh consolidation
thread. Their order is explicit, while one short current instruction can define
the synthesis task.

A full checkpoint includes the donor's retained messages and is useful when
testing a close clone or recovery. It is not a history replacement: Codex still
appends those items after the target's own initial context. Use a fresh target
and inspect the result rather than calling it an exact clone.
