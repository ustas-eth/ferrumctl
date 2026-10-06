<!-- Generated from packages/codex-goalctl/docs/app-server-boundaries.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

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

Current Codex permits goal reads on parent-owned v2 children but rejects
external goal changes. Their native parent workflow owns assignment and
lifecycle. When a host process or another thread needs direct goal control,
create an independent root through threadctl and retain its thread id. Resolving
a canonical task name or resuming a child does not transfer ownership.

## Wake Boundary

Changing a goal does not reliably wake a CLI-owned thread. A worker may not act
on the new goal until it receives another input turn or is otherwise resumed.

Use native subagent input when a native subagent handle is available. For an
independent root, `codex-threadctl wake THREAD_ID --resume` can continue from
the assigned goal without adding user input, when immediate thread control is
available. Reapply any creation configuration file if cold loading needs those
overrides. Agent requests or corrections can use `send --wake`; conditional or
delayed delivery remains a separate scheduler concern.
