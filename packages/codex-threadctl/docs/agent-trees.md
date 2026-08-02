# Spawned-Agent Trees

This reference describes how `codex-threadctl` maps persisted spawn
relationships, v2 agent paths, and app-server input ownership.

## Identity

Every spawned agent has a thread id. Codex v2 also assigns a path such as
`/root/reviewer` that identifies the agent's place in one native spawn tree.
Thread ids are persisted identities. Agent paths are tree-local handles and can
be reused after an agent closes.

`agents` accepts any thread id in a tree, follows its parent lineage to the
root, and lists the root plus persisted descendants. It also accepts a path
when `CODEX_THREAD_ID` or `--tree` supplies the tree scope:

```sh
codex-threadctl agents THREAD_ID
codex-threadctl agents /root/reviewer --tree THREAD_ID
```

The root is shown as `/root`. V1 agents have no native path and remain
addressable by thread id. Closed agents can remain in the persisted tree even
after their native handles are gone; `loaded` and `status` report separate
app-server state.

## Path Resolution

`resolve` maps one exact path to its thread id:

```sh
codex-threadctl resolve /root/reviewer
codex-threadctl resolve /root/reviewer --tree THREAD_ID
```

`CODEX_THREAD_ID` supplies the tree scope when present. Otherwise `--tree` can
name any thread id in the intended tree. With neither scope, resolution searches
loaded threads only and succeeds only for one exact match.

Threadctl commands that accept a thread id also accept `/root` paths under the
same rules:

```sh
codex-threadctl inspect /root/reviewer
codex-threadctl messages /root/reviewer --limit 10
```

Resolution fails when a path is absent or matches more than one persisted
thread. This can happen after path reuse. Use `agents` to inspect the candidates
and retain the selected thread id for durable state or later commands.

Other ferrumctl packages continue to use thread ids unless they explicitly
document path support. This keeps stored goals, snapshots, and other records
bound to a stable identity rather than a reusable path.

## Input Ownership

`agents`, `list`, `status`, and `inspect` expose `inputOwner`:

- `direct` means app-server reports that direct turn input is accepted.
- `parent` means the v2 native parent owns lifecycle input.
- `unknown` means the capability was not available from the selected server.

For `parent` agents, Codex rejects direct `start`, `steer`, and idle `wake`.
Use the native parent handle to start or continue their work. Thread inspection,
retained history, goal access by thread id, and exact interruption remain
separate surfaces. `notify` uses advisory item injection: it can affect active
reasoning, but does not start or steer a turn or provide lifecycle control.

Resuming or loading a child does not transfer input ownership. The app-server's
reported capability and native rejection remain authoritative.

## Scheduled Conditions

Wakectl can resolve v2 paths when a job or synchronous wait is created. A child
can be the subject of a goal or stop condition, while delivery targets must
accept direct input:

```sh
codex-wakectl add goal /root/reviewer --status complete,blocked \
  --to /root "Automated event: Reviewer goal ended."
```

The resolved thread ids are stored in the job. Later path reuse does not retarget
it. A parent-owned path is rejected as a delivery target; a job created with the
same child as a raw thread id becomes failed if app-server later rejects direct
delivery.
