<!-- Generated from packages/codex-threadctl/docs/agent-trees.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Spawned-Agent Trees

This reference describes how `codex-threadctl` maps persisted spawn
relationships, canonical task names, and app-server input ownership.

## Independent Roots

`create` calls app-server `thread/start` and returns a new persisted root thread:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project)
```

This is the canonical worker shape when a host process or another thread must
apply direct app-server control. The root is not a child in the caller's native
agent tree. It therefore has no parent handle, canonical task name, or automatic
result routing; its thread id is the control handle.

Creating a root does not start a turn or assign a goal. It adds a short
`threadctl` advisory item to persist the new transcript. The root initially
belongs to the selected app-server, but can later become `notLoaded` like any
thread after its subscribers leave. Its persisted identity remains available
for inspection or explicit resume.

## Identity

Every spawned agent has a thread id. Some native subagent tools also expose a
canonical task name such as `/root/reviewer`, identifying the agent's place in
one spawn tree. Persisted app-server metadata calls this `agent_path`; threadctl
JSON exposes it as `agentPath`. A thread id is a persisted identity; a canonical
task name is a tree-local routing handle and can be reused after an agent closes.

`agents` accepts any thread id in a tree, follows its parent lineage to the
root, and lists the root plus persisted descendants. It also accepts a canonical
task name when `CODEX_THREAD_ID` or `--tree` supplies the tree scope:

```sh
codex-threadctl agents THREAD_ID
codex-threadctl agents /root/reviewer --tree THREAD_ID
```

The root is shown as `/root`. Ferrumctl accepts only canonical names beginning
with `/root`, not relative task names. V1 agents have no canonical task name and
remain addressable by thread id. Closed agents can remain in the persisted tree
even after their native handles are gone; `loaded` and `status` report separate
app-server state.

## Task Name Resolution

`resolve` maps one exact canonical task name to its thread id:

```sh
codex-threadctl resolve /root/reviewer
codex-threadctl resolve /root/reviewer --tree THREAD_ID
```

`CODEX_THREAD_ID` supplies the tree scope when present. Otherwise `--tree` can
name any thread id in the intended tree. With neither scope, resolution searches
loaded threads only and succeeds only for one exact match.

Threadctl commands that accept a thread id also accept canonical task names
under the same rules:

```sh
codex-threadctl inspect /root/reviewer
codex-threadctl messages /root/reviewer --limit 10
```

Resolution fails when a task name is absent or matches more than one persisted
thread. This can happen after name reuse. Use `agents` to inspect the candidates
and retain the selected thread id for durable state or later commands. An
unambiguous canonical task name can be used directly for an immediate threadctl
operation; resolving it first adds no ownership or delivery guarantee.

Other ferrumctl packages continue to use thread ids unless they explicitly
document canonical task name support. This keeps stored goals, snapshots, and
other records bound to a stable identity rather than a reusable routing name.

## Input Ownership

`agents`, `list`, `status`, and `inspect` expose `inputOwner`:

- `direct` means app-server reports that direct turn input is accepted.
- `parent` means the native parent owns lifecycle input.
- `unknown` means the capability was not available from the selected server.

For `parent` agents, current Codex rejects direct `start`, `steer`, idle `wake`,
and advisory `notify`. It also reserves external goal changes and raw context
injection for the native owner. Use the native parent handle to continue or stop
the child. Read-only inspection, retained history, goal reads, condition
observation, and exact interruption remain separate surfaces.

Resuming or loading a child does not transfer input ownership. The app-server's
reported capability and native rejection remain authoritative. If direct
external control is required, create an independent root from the outset rather
than trying to convert an existing child.

## Scheduled Conditions

Wakectl can resolve canonical task names when a job or synchronous wait is
created. A child can be the subject of a goal or stop condition, while delivery
targets must accept direct input:

```sh
codex-wakectl add goal /root/reviewer --status complete,blocked \
  --to /root
```

The resolved thread ids are stored in the job. Later task name reuse does not
retarget it. A parent-owned child is rejected as a delivery target when selected
by canonical task name; a job created with the same child as a raw thread id
becomes failed if app-server later rejects direct delivery.
