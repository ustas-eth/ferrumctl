---
name: codex-memoryctl
description: "Use when opaque Codex compaction memory must be inspected or reused for older-self recall, consultation with another thread's retained perspective, or seeding a fresh handoff, consolidation, or recovery thread. Do not use for ordinary messages, conversation reading, requesting compaction, or durable project knowledge."
---

# Codex Memoryctl

Use `codex-memoryctl` to reuse opaque memory already created by Codex
compaction. It reads local rollouts and keeps no state of its own.

## Choose The Workflow

Inspect available memory without exposing its encrypted content:

```sh
codex-memoryctl list THREAD_ID
codex-memoryctl show THREAD_ID@latest
codex-memoryctl search THREAD_ID "earlier diagnosis"
```

`visible=yes` means that observation remains in the thread's current
model-visible history. It does not prove that the model used it.

`search` finds ordinary transcript text and reports the first later portable
checkpoint. Its default token mode can match words across messages in one
checkpoint segment; use `--match phrase` or `--match regex` when exact matching
matters. `uncompacted` means no existing memory can contain that transcript
tail. Search associates text with checkpoints; it does not inspect ciphertext.

For a foreign perspective, prefer a disposable consultant when the established
agent should keep its trajectory. Frame the question in a fresh thread, then
have that thread assimilate the donor memory itself:

```sh
codex-memoryctl inject --self \
  --state DONOR_THREAD_ID@latest \
  --purpose "Consult this perspective for the handoff question in my current turn."
```

Use `--self` in an established thread only when durable assimilation is
intended, such as older-self recall. It requires an active `CODEX_THREAD_ID`
and `--purpose`, binds memory to the current turn, and appends the exact purpose
and canonical memory references as an attributed item after the opaque batch.
State how the memory relates to the current question; do not infer a donor role
or assignment merely to fill the purpose.

Use `--to TARGET` for source-associated transplantation into a loaded thread.
This is suitable for a fresh handoff or recovery target; it should not be
treated as neutral context for an established agent. Full-checkpoint transfer
requires `--to` and is intended for a fresh target.

Use several `--state` arguments for one ordered memory-only batch. Use
`--full-checkpoint` only when the donor's retained user, developer, and agent
messages are needed as well. An exported file preserves the same distinction.

```sh
codex-memoryctl export DONOR_THREAD_ID@latest --output memory.json
codex-memoryctl inject --self --file memory.json \
  --purpose "Recall the diagnosis retained in this exported memory."
```

The memory itself carries no reliable donor identity, purpose, or added
authority. Current-turn binding gives it surrounding provenance, not
isolation: content and order can still redirect the recipient. Keep current
instructions and current evidence authoritative, and extract what is useful
instead of reviving obsolete work.

## Judge The Lifecycle

- Once recorded, injected memory has no paired removal operation. A later
  compaction may assimilate it into this thread's next opaque memory.
- An idle injection is recorded immediately. During an active turn it first
  enters pending input and may not appear in the rollout until Codex processes
  it.
- The target must be loaded on the selected app-server. Injection neither
  wakes it nor starts a turn.
- `accepted` confirms only the app-server request. It does not prove model
  receipt, interpretation, or action.
- An uncertain request may already have succeeded. Compare the reported memory
  reference with `list TARGET` before retrying.
- Known non-OpenAI targets are incompatible by default. An OpenAI provider
  passes the transport check, but useful interpretation across models is not
  guaranteed; validate a cross-model workflow before relying on it.

Both v1 and v2 agents use thread ids and local rollouts. Canonical task names
such as `/root/reviewer` are accepted when they resolve unambiguously in the
current tree. Preserve a thread id when the reference must remain durable.

## References

- Read `references/memory-model.md` when checkpoint contents, selectors,
  visibility, digests, rollout sources, or v1/v2 storage matter.
- Read `references/injection-semantics.md` before automating injection,
  interpreting acceptance, or handling an uncertain outcome.
- Read `references/memory-workflows.md` when choosing among consultation,
  older-self recall, handoff, consolidation, and recovery.
- Read `references/coordination-principles.md` when composing memory transfer
  with other ferrumctl state or lifecycle tools.
