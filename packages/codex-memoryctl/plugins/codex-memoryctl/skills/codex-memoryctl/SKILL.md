---
name: codex-memoryctl
description: "Use when existing opaque Codex compaction memory must be located, compared by digest, exported, or deliberately injected into a loaded Codex thread for recall, consultation, cloning, consolidation, or compaction experiments. Do not use for ordinary messages, conversation reading, requesting compaction, or durable project knowledge."
---

# Codex Memoryctl

Use `codex-memoryctl` to work with opaque memory already created by Codex
compaction. It reads local rollouts and keeps no state of its own.

## Choose The Transfer

Inspect available memory without exposing its encrypted content:

```sh
codex-memoryctl list THREAD_ID
codex-memoryctl show THREAD_ID@latest
```

For an in-place consultation, state the purpose in your current reasoning and
call the command yourself. The target defaults to `CODEX_THREAD_ID`:

```sh
codex-memoryctl inject \
  --state DONOR_THREAD_ID@latest \
  --purpose "Consult this perspective while retaining my current role and goal."
```

Omit the target for self-consultation. Memoryctl verifies that this thread has
an active turn and binds the copied memories to that turn instead of retaining
their donor turn associations. An explicit target preserves source association;
a full checkpoint requires an explicit fresh target.

The tool call gives the donated memory useful provenance in this thread's
surrounding context. The memory itself carries no reliable donor identity,
purpose, or added authority. Current-turn binding is framing, not isolation:
memory content and order can still redirect the recipient. Use a disposable
consultation thread when the original must remain unchanged; thread creation
and result retrieval remain native operations.

Use several `--state` arguments for one ordered memory-only batch. Use
`--full-checkpoint` only when a fresh target deliberately needs the donor's
retained user, developer, and agent messages as well. An exported file preserves
the same distinction.

```sh
codex-memoryctl export DONOR_THREAD_ID@latest --output memory.json
codex-memoryctl inject --file memory.json
```

`--purpose` is part of the command receipt. It is visible in your own tool call,
but it does not send an instruction to a different target.

## Judge The Lifecycle

- An idle injection is recorded immediately. During an active turn it first
  enters pending input and may not appear in the rollout until Codex processes
  it. Once recorded, it has no paired removal operation.
- A later compaction may assimilate the donated state into this thread's next
  opaque memory.
- The target must be loaded on the selected app-server. Injection neither
  wakes it nor starts a turn.
- `accepted` confirms only the app-server request. It does not prove model
  receipt, interpretation, or action.
- An uncertain request may already have succeeded. Compare the reported memory
  reference with `list TARGET` before retrying.
- Known non-OpenAI targets are incompatible by default. Override that check
  only for a deliberate provider experiment.

Both v1 and v2 agents use thread ids and local rollouts. Canonical task names
such as `/root/reviewer` are accepted when they resolve unambiguously in the
current tree. Preserve a thread id when the reference must remain durable.

## References

- Read `references/memory-model.md` when checkpoint contents, selectors,
  digests, rollout sources, or v1/v2 storage matter.
- Read `references/injection-semantics.md` before automating injection,
  interpreting acceptance, or handling an uncertain outcome.
- Read `references/memory-workflows.md` when choosing between in-place recall,
  a disposable consultant, cloning, or multi-memory consolidation.
- Read `references/coordination-principles.md` when composing memory transfer
  with other ferrumctl state or lifecycle tools.
