<!-- Generated from packages/codex-threadctl/docs/agent-trees.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Spawned-Agent Trees

This reference describes how `codex-threadctl` maps persisted spawn
relationships, canonical task names, and app-server input ownership.

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

For `parent` agents, Codex rejects direct `start`, `steer`, and idle `wake`.
Use the native parent handle to start or continue their work. Thread inspection,
retained history, goal access by thread id, and exact interruption remain
separate surfaces. `notify` uses advisory item injection: it can affect active
reasoning, but does not start or steer a turn or provide lifecycle control.

Resuming or loading a child does not transfer input ownership. The app-server's
reported capability and native rejection remain authoritative.

## Scheduled Conditions

Wakectl can resolve canonical task names when a job or synchronous wait is
created. A child can be the subject of a goal or stop condition, while delivery
targets must accept direct input:

```sh
codex-wakectl add goal /root/reviewer --status complete,blocked \
  --to /root "Automated event: Reviewer goal ended."
```

The resolved thread ids are stored in the job. Later task name reuse does not
retarget it. A parent-owned child is rejected as a delivery target when selected
by canonical task name; a job created with the same child as a raw thread id
becomes failed if app-server later rejects direct delivery.
