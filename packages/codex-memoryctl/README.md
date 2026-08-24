# codex-memoryctl

`codex-memoryctl` lets you inspect, export, and deliberately inject the opaque
memory that Codex creates during compaction.

This makes controlled experiments possible on real Codex threads: an agent can
consult another thread's compacted perspective, revisit an older checkpoint,
or seed a disposable consolidation thread with several memories. The command
uses local rollout files as its source and a shared Codex app-server for
injection. It keeps no database or background service.

The feature is experimental. Injected memory becomes part of the target's
model-visible history and has no automatic removal operation.

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

List the latest memory observations for a thread:

```sh
codex-memoryctl list THREAD_ID
codex-memoryctl show THREAD_ID@latest
codex-memoryctl show THREAD_ID@window:14 --json
```

By default, injection copies only the opaque compaction item. When
`CODEX_THREAD_ID` is available, the target defaults to the calling thread:

```sh
codex-memoryctl inject \
  --state DONOR_THREAD_ID@latest \
  --purpose "Consult this diagnosis while retaining my current role and goal."
```

With the target omitted, the calling thread must have an active turn. The
command binds the copied memories to that turn instead of retaining their donor
turn associations. Several `--state` arguments form one ordered batch:

```sh
codex-memoryctl inject \
  --state HUNTER_THREAD_ID@latest \
  --state ENGINEER_THREAD_ID@latest \
  --purpose "Compare these peer perspectives against my current work."
```

Export a portable memory file without printing its encrypted content:

```sh
codex-memoryctl export THREAD_ID@latest --output memory.json
codex-memoryctl inject --file memory.json
```

Use `--full-checkpoint` only when retained user, developer, and agent messages
are intentionally part of a cloning or restoration experiment:

```sh
codex-memoryctl export THREAD_ID@latest \
  --full-checkpoint --output checkpoint.json
codex-memoryctl inject FRESH_THREAD_ID \
  --state THREAD_ID@latest --full-checkpoint
```

The export is written with private file permissions. Passing `--output -`
explicitly writes the complete object to stdout.

## Boundaries

- Injection appends model-visible history; it does not replace the target's
  history, wake it, or start a turn.
- An omitted target is an active self-consultation and receives current-turn
  binding. An explicit target preserves the source turn association.
- An active target first receives pending input, which may not appear in the
  rollout until Codex processes it. An idle target records the items for a
  later turn immediately.
- App-server acceptance does not prove that the model interpreted the memory.
- The opaque item carries no reliable donor identity or purpose. A receiving
  agent should request an in-place consultation from its own context.
- Later compaction may absorb an injected memory into the target's next
  checkpoint. Use a disposable thread when the original must remain unchanged.
- `list` and `show` never print encrypted content. Full-checkpoint exports can
  contain retained plaintext messages and should be treated as sensitive.

More detail:

- [Memory model](docs/memory-model.md)
- [Injection semantics](docs/injection-semantics.md)
- [Memory workflows](docs/memory-workflows.md)

## Codex Skill

Install the optional skill when Codex should know when and how to use memory
injection:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-memoryctl@ferrumctl
```

The skill lives at
`plugins/codex-memoryctl/skills/codex-memoryctl/SKILL.md`.
