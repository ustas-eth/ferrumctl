# codex-memoryctl

`codex-memoryctl` lets Codex agents locate, describe, compare, and reuse the
opaque memory created during compaction. It can build a compact, grep-friendly
view of a long thread, revisit an older checkpoint, let a fresh consultant
consider another thread's retained perspective, or seed a handoff or recovery
thread with selected prior memory.

Structural inspection reads local rollout files without a model request.
Generated descriptions use Codex subscription auth and are cached as plaintext
in a private SQLite database. Injection uses a shared Codex app-server. The
command has no background service. Injection relies on evolving Codex
app-server and compaction formats, so compatibility should be checked after
Codex upgrades.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-memoryctl
```

From this package directory:

```sh
uv tool install .
```

Injection requires Codex 0.148 or newer and a target loaded on the selected
app-server.

## Examples

List memory observations without printing their encrypted content:

```sh
codex-memoryctl list THREAD_ID
codex-memoryctl list THREAD_ID --limit 0
codex-memoryctl show THREAD_ID@latest
codex-memoryctl show THREAD_ID@window:14 --json
```

Each observation reports whether it remains in the thread's current
model-visible history. Visibility does not prove that the model used it.
`list` shows the newest 20 matching observations by default and reports the
complete inventory separately: selected and matching counts, total
compactions, and the first and last reusable checkpoint indices. Those indices
are positions among all compactions, so older compactions without reusable
opaque memory can make the range begin above one or contain gaps. JSON keeps
the observations under `states` and exposes the inventory counts alongside it.

Generate a short description of one checkpoint, compare two checkpoints, or
render a sequential view of the whole thread:

```sh
codex-memoryctl summarize THREAD_ID@latest
codex-memoryctl diff THREAD_ID@index:12 THREAD_ID@index:13
codex-memoryctl index THREAD_ID
codex-memoryctl index THREAD_ID --limit 0 | rg -i "preset|aggregator"
codex-memoryctl index THREAD_ID --limit 0 --no-records
```

`summarize` and `diff` produce one concise text field. `index` summarizes the
first portable checkpoint and describes each later checkpoint relative to its
predecessor. It renders the newest ten matching checkpoints by default;
`--limit 0` deliberately selects the complete range. Use `--from-index` and
`--to-index` for checkpoint bounds or `--since` and `--until` for UTC dates and
RFC3339 timestamps. Bounds and limits apply before model requests.
`--no-records` still generates and caches every selected card but returns only
counts and bounds. It reports bounded progress on stderr, which is useful when
preparing a large index without placing every generated description in the
caller's context.

The view joins the current rollout with cached results rather than maintaining
a separate catalog. It reports when ordinary conversation follows the newest
compaction because those messages are not described by the index. It also
warns when the newest compaction has no portable memory. `summarize` gives the
tail warning when its selected state is the latest checkpoint. The default
model is GPT-5.6 Luna at medium effort;
`--model`, `--effort`, and `--refresh` are available when a different tradeoff
or a fresh result is needed. Use `--no-cache` to generate without reading or
writing the plaintext cache.

Generated text is a model-derived aid for orientation and search. It may omit
retained details, so an omission is not evidence that the opaque state lacks
them. The cache defaults to
`$XDG_STATE_HOME/codex-memoryctl/derived.sqlite3`, or
`~/.local/state/codex-memoryctl/derived.sqlite3`, and should be treated as
sensitive session material. Inspect or remove its derived contents explicitly:

```sh
codex-memoryctl cache info
codex-memoryctl cache clear
```

Find which memory checkpoints followed relevant transcript text:

```sh
codex-memoryctl search THREAD_ID "preset mismatch"
codex-memoryctl search THREAD_ID "exact phrase" --match phrase
codex-memoryctl search THREAD_ID 'preset.*mismatch' --match regex
```

The default token search can match words across messages in one checkpoint
segment. Results identify the first later portable checkpoint and show ordinary
nearby messages. `uncompacted` means the matching text has no later memory
checkpoint yet. Search does not inspect the encrypted memory itself.

For consultation or older-self recall, the receiving agent adds memory to its
own active turn and records how it relates to the current question:

```sh
codex-memoryctl inject --self \
  --state DONOR_THREAD_ID@latest \
  --purpose "Compare this diagnosis with the evidence in my current investigation."
```

`--self` is the recipient-owned preset: it requires an active
`CODEX_THREAD_ID`, direct app-server injection, and a purpose. It binds the
memory to the current turn and adds source boundaries. When another established
agent should use a memory, give it the reference and question so it can run this
command itself. Use a disposable consultant when the original conversation
should remain unchanged.

Several `--state` arguments form one ordered batch. Memoryctl closes one
attributed perspective before opening the next, but the model may still combine
or confuse their contents.

`--to TARGET` transfers memory externally to a loaded target that accepts direct
app-server injection. It preserves source turn association and adds the same
boundaries by default. A caller that expects no materialized target turns yet
can request that precondition:

```sh
codex-memoryctl inject --to FRESH_THREAD_ID \
  --state DONOR_THREAD_ID@latest \
  --purpose "Use this perspective for the handoff question." \
  --expect-no-turns --preview
codex-memoryctl inject --to FRESH_THREAD_ID \
  --state DONOR_THREAD_ID@latest \
  --purpose "Use this perspective for the handoff question." \
  --expect-no-turns
```

`--preview` performs the read-only preflight and reports memory count, opaque
payload bytes, source items, framing items, retained items for a full
checkpoint, and the resulting item count. It does not estimate model tokens or
reserve the target state; repeat the command without `--preview` to submit it.

Current Codex rejects injection into parent-owned v2 children, including a
child invoking `--self`. Use an independently controlled root or disposable
consultant when memory injection is required.

With `--to`, low-level callers can choose `--binding source|current` and
`--framing boundaries|none`. Current binding requires an active target turn.
Unframed transfer adds no source boundary and therefore accepts no purpose.

Export a portable memory file without printing its encrypted content:

```sh
codex-memoryctl export THREAD_ID@latest --output memory.json
codex-memoryctl inject --self --file memory.json \
  --purpose "Recall the diagnosis retained in this exported memory."
```

A full checkpoint is useful when a fresh recovery target needs the donor's
retained user, developer, and agent messages:

```sh
codex-memoryctl export THREAD_ID@latest \
  --full-checkpoint --output checkpoint.json
codex-memoryctl inject --to FRESH_THREAD_ID \
  --file checkpoint.json --expect-no-turns
```

Exports are written with private file permissions. Passing `--output -`
explicitly writes the complete object to stdout.

## Boundaries

- Injection appends model-visible history; it does not replace history, wake a
  thread, or start a turn.
- `--self` selects current-turn binding and source boundaries. `--to` defaults
  to source binding and boundaries while exposing both choices explicitly.
- Perspective boundaries improve provenance but do not isolate foreign memory
  or guarantee interpretation. Unframed transfer is available when the caller
  needs the underlying append primitive.
- A model can use imported memory without retaining awareness that it came from
  another perspective. State the intended relationship positively and use a
  disposable consultant when the original thread must remain unchanged.
- During an active turn, injected memory first enters pending input and may not
  appear in the rollout until Codex processes it. An idle target records it
  immediately for a later turn.
- App-server acceptance does not prove that the model interpreted the memory.
- Preview counts describe the proposed item batch, not its eventual context
  token cost or a guarantee that the later submission will see the same state.
- Opaque memory carries no reliable donor identity or purpose. Boundary framing
  adds source labels around it without changing the object.
- Later compaction may absorb injected memory into the target's next
  checkpoint, and there is no paired removal operation.
- Export digests validate the opaque item. Exported source thread, time, model,
  and checkpoint fields remain editable claims.
- Full-checkpoint exports contain retained plaintext messages. Treat every
  export as sensitive session material.

More detail:

- [Memory model](docs/memory-model.md)
- [Injection semantics](docs/injection-semantics.md)
- [Memory workflows](docs/memory-workflows.md)
- [Perspective framing](docs/perspective-framing.md)
- [Generated text](docs/generated-text.md)

## Codex Skill

Install the optional skill when Codex should choose and operate these memory
workflows:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-memoryctl@ferrumctl
```

The skill lives at
`plugins/codex-memoryctl/skills/codex-memoryctl/SKILL.md`.
