# App Server Boundaries

This reference describes how `codex-goalctl` reaches Codex goal state and where
that control stops.

## Transport

Each invocation starts:

```sh
codex app-server --listen stdio://
```

The command initializes that app-server, performs one goal operation, and exits.
Normal `codex-goalctl` use therefore does not require a shared unix app-server
or any long-running service.

Use `--codex-bin` or `CODEX_BIN` when a different `codex` executable should be
used. Use `--timeout` or `CODEX_GOALCTL_TIMEOUT` when app-server calls need more
time.

## App-Server Methods

`codex-goalctl` uses only Codex goal methods:

- `thread/goal/get`
- `thread/goal/set`
- `thread/goal/clear`

It does not call spawn, send-input, wait, or transcript APIs. This keeps the CLI
limited to goal state.

## Thread IDs

The caller must already know the target thread id. For v1 Codex subagents, the
spawn result's `agent_id` is the thread id.

Some native subagent tools return a canonical task name such as
`/root/reviewer`. It is a tree-local routing handle rather than a goal
identifier. Resolve the task name through a tree-aware tool when available,
then retain the thread id for goal operations. Goalctl deliberately does not
depend on a shared app-server or resolve canonical task names itself.

The target must be reachable to the Codex instance started by the command. In
practice, that means the same Codex home/configuration and a valid persisted
thread id.

## Wake Boundary

Changing a goal does not reliably wake a CLI-owned thread. A worker may not act
on the new goal until it receives another input turn or is otherwise resumed.

After assigning work, send a small normal message when the worker should act
immediately:

```text
From coordinator: A goal was assigned. Call get_goal and proceed.
```

Use native subagent input when a native subagent handle is available. Use
`codex-threadctl start` when immediate thread-id control is available and the
worker is loaded on the selected shared app-server. Conditional or delayed
delivery remains a separate scheduler concern. The source label distinguishes
the follow-up from direct human input; it does not prove identity or override
existing instructions.
