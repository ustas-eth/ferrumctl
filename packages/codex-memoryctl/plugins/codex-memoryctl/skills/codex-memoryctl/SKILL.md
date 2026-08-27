---
name: codex-memoryctl
description: "Use when opaque Codex compaction memory must be located, described, compared, indexed, or reused for older-self recall, consultation with another thread's retained perspective, or seeding a fresh handoff, consolidation, or recovery thread. Do not use for ordinary messages, exact conversation reading, requesting compaction, or durable project knowledge."
---

# Codex Memoryctl

Use `codex-memoryctl` to find, interpret, or reuse opaque memory already created
by Codex compaction. Structural operations read local rollouts. Generated
descriptions use a model and keep a private plaintext cache.

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

When the words are unknown, use model-derived text to orient or search:

```sh
codex-memoryctl summarize THREAD_ID@latest
codex-memoryctl diff THREAD_ID@index:12 THREAD_ID@index:13
codex-memoryctl index THREAD_ID
codex-memoryctl index THREAD_ID --limit 0 | rg -i "suspected subject"
```

Use `summarize` for one checkpoint, `diff` for a directed comparison, and
`index` for a compact sequential view. Index renders the newest ten matching
checkpoints by default; use `--from-index`, `--to-index`, `--since`, or
`--until` to browse, and use `--limit 0` only when the complete range is
needed. Selection happens before model requests. If index reports an
uncompacted tail, inspect that conversation separately rather than treating the
newest card as current thread state.

These commands make subscription model requests on cache misses. Their
plaintext is useful for locating a likely state, not for proving that an
omitted detail is absent. Use `--focus` only when the current question gives a
real subject to emphasize. Use `--no-cache` when generated text should not
persist locally. If the task needs the opaque state's retained fidelity, use an
appropriate consultation or recall workflow instead of treating generated text
as equivalent memory.

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
in the closing perspective boundary. Memoryctl labels each imported memory with
its source reference and whether that source came from a local rollout or an
export claim. State how the retained perspective relates to the current
question; do not infer a donor role or assignment merely to fill the purpose.

Use `--to TARGET` for source-associated transplantation into a loaded thread.
Memory-only transfer uses the same perspective boundaries and delivers an
optional purpose after the batch. This is suitable for a fresh handoff or
recovery target; it should not be treated as neutral context for an established
agent. Full-checkpoint transfer requires `--to`, remains unframed, and is
intended for a fresh target.

Use several `--state` arguments for one ordered memory-only batch. Use
`--full-checkpoint` only when the donor's retained user, developer, and agent
messages are needed as well. An exported file preserves the same distinction.
Memoryctl closes one imported perspective before opening the next. This
improves attribution, but order and content can still blur or redirect the
recipient.

```sh
codex-memoryctl export DONOR_THREAD_ID@latest --output memory.json
codex-memoryctl inject --self --file memory.json \
  --purpose "Recall the diagnosis retained in this exported memory."
```

An export's opaque digest is validated. Its source thread, time, model, and
checkpoint fields remain editable metadata rather than authenticated
provenance.

The memory itself carries no reliable donor identity, purpose, or added
authority. The attributed boundaries give it surrounding provenance, not
isolation. Keep current instructions and current evidence authoritative, and
extract what is useful instead of reviving obsolete work.

Usable memory and source awareness are separate. When a donor should remain a
foreign perspective, state that relationship positively; do not ask the model
to prove it can inspect ciphertext or rely on rejecting the donor identity to
create separation. Prefer a disposable consultant when the established thread
must remain unchanged.

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
- Read `references/perspective-framing.md` when imported memory should remain a
  distinguishable perspective or several memories must retain attribution.
- Read `references/generated-text.md` when model requests, source boundaries,
  caching, index construction, or generated-text limitations matter.
- Read `references/coordination-principles.md` when composing memory transfer
  with other ferrumctl state or lifecycle tools.
