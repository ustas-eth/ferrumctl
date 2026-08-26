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
codex-memoryctl show THREAD_ID@latest
codex-memoryctl show THREAD_ID@window:14 --json
```

Each observation reports whether it remains in the thread's current
model-visible history. Visibility does not prove that the model used it.

Generate a short description of one checkpoint, compare two checkpoints, or
render a sequential view of the whole thread:

```sh
codex-memoryctl summarize THREAD_ID@latest
codex-memoryctl diff THREAD_ID@index:12 THREAD_ID@index:13
codex-memoryctl index THREAD_ID | rg -i "preset|aggregator"
```

`summarize` and `diff` produce one concise text field. `index` summarizes the
first portable checkpoint and describes each later checkpoint relative to its
predecessor. It renders the current rollout together with cached results rather
than maintaining a separate catalog. The default model is GPT-5.6 Luna at
medium effort; `--model`, `--effort`, and `--refresh` are available when a
different tradeoff or a fresh result is needed.

Generated text is a model-derived aid for orientation and search. It may omit
retained details, so an omission is not evidence that the opaque state lacks
them. The cache defaults to
`$XDG_STATE_HOME/codex-memoryctl/derived.sqlite3`, or
`~/.local/state/codex-memoryctl/derived.sqlite3`, and should be treated as
sensitive session material.

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

For consultation or older-self recall, the receiving agent injects memory into
its own active turn and records why:

```sh
codex-memoryctl inject --self \
  --state DONOR_THREAD_ID@latest \
  --purpose "Compare this diagnosis with the evidence in my current investigation."
```

Several `--state` arguments form one ordered memory-only batch:

```sh
codex-memoryctl inject --self \
  --state HUNTER_THREAD_ID@latest \
  --state ENGINEER_THREAD_ID@latest \
  --purpose "Compare these perspectives against my current evidence."
```

Memoryctl labels the first perspective, closes it before opening the next, and
closes the final perspective with the caller purpose. Each boundary carries
the relevant source reference and whether it came from a local rollout or an
export claim. This improves attribution without guaranteeing that the model
will keep the perspectives separate.

`--self` requires an active `CODEX_THREAD_ID` and uses current-turn binding. It
also frames the opaque batch with attributed source items. Use `--to TARGET`
when a fresh loaded thread should retain the source turn association;
memory-only transfers keep the same perspective framing:

```sh
codex-memoryctl inject --to FRESH_THREAD_ID \
  --state DONOR_THREAD_ID@latest
```

Export a portable memory file without printing its encrypted content:

```sh
codex-memoryctl export THREAD_ID@latest --output memory.json
codex-memoryctl inject --self --file memory.json \
  --purpose "Recall the diagnosis retained in this exported memory."
```

Use a full checkpoint only when the donor's retained user, developer, and
agent messages are needed for a fresh recovery target:

```sh
codex-memoryctl export THREAD_ID@latest \
  --full-checkpoint --output checkpoint.json
codex-memoryctl inject --to FRESH_THREAD_ID \
  --state THREAD_ID@latest --full-checkpoint
```

Exports are written with private file permissions. Passing `--output -`
explicitly writes the complete object to stdout.

## Boundaries

- Injection appends model-visible history; it does not replace history, wake a
  thread, or start a turn.
- `--self` binds memory to the caller's current turn. `--to` preserves source
  turn association.
- Memory-only transfers use attributed perspective boundaries. They improve
  provenance but do not isolate foreign memory or guarantee interpretation.
- A model can use imported memory without retaining awareness that it came from
  another perspective. State the intended relationship positively and use a
  disposable consultant when the original thread must remain unchanged.
- During an active turn, injected memory first enters pending input and may not
  appear in the rollout until Codex processes it. An idle target records it
  immediately for a later turn.
- App-server acceptance does not prove that the model interpreted the memory.
- Opaque memory carries no reliable donor identity or purpose; memoryctl adds
  source labels around it rather than changing the object.
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
