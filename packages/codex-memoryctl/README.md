# codex-memoryctl

`codex-memoryctl` lets Codex agents inspect and reuse the opaque memory created
during compaction. A long-running agent can revisit an older checkpoint, a
fresh consultant can consider another thread's retained perspective, and a
new handoff or recovery thread can start with selected prior memory.

The command reads local rollout files and uses a shared Codex app-server for
injection. It keeps no database or background service. Injection relies on
evolving Codex app-server and compaction formats, so compatibility should be
checked after Codex upgrades.

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

For consultation or older-self recall, the receiving agent injects memory into
its own active turn and records why:

```sh
codex-memoryctl inject --self \
  --state DONOR_THREAD_ID@latest \
  --purpose "Consult this diagnosis while retaining my current role and goal."
```

Several `--state` arguments form one ordered memory-only batch:

```sh
codex-memoryctl inject --self \
  --state HUNTER_THREAD_ID@latest \
  --state ENGINEER_THREAD_ID@latest \
  --purpose "Compare these perspectives against my current evidence."
```

`--self` requires an active `CODEX_THREAD_ID` and uses current-turn binding.
Use `--to TARGET` when a fresh loaded thread should retain the source turn
association:

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
- During an active turn, injected memory first enters pending input and may not
  appear in the rollout until Codex processes it. An idle target records it
  immediately for a later turn.
- App-server acceptance does not prove that the model interpreted the memory.
- Opaque memory carries no reliable donor identity or purpose. Use a disposable
  consultant when an established thread should remain unchanged.
- Later compaction may absorb injected memory into the target's next
  checkpoint, and there is no paired removal operation.
- Full-checkpoint exports contain retained plaintext messages. Treat every
  export as sensitive session material.

More detail:

- [Memory model](docs/memory-model.md)
- [Injection semantics](docs/injection-semantics.md)
- [Memory workflows](docs/memory-workflows.md)

## Codex Skill

Install the optional skill when Codex should choose and operate these memory
workflows:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-memoryctl@ferrumctl
```

The skill lives at
`plugins/codex-memoryctl/skills/codex-memoryctl/SKILL.md`.
