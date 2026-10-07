# App Server Boundaries

This reference describes how `codex-goalctl` reaches Codex goal state and where
that control stops.

## Transport

By default, goalctl checks the shared server at `unix://`. If that server holds
the target thread, the goal operation uses the same connection. If the socket
is absent, refuses connection, or does not hold the target, goalctl starts:

```sh
codex app-server --listen stdio://
```

This standalone server performs the goal operation and exits. It provides
persisted-state access without requiring a long-running service. Goalctl does
not load the target merely to select a transport.

Use `--codex-bin` or `CODEX_BIN` when a different `codex` executable should be
used for standalone operation.

For a thread running on a different app-server, select that server explicitly:

```sh
codex-goalctl update THREAD_ID --token-budget 500000 --endpoint unix:///path/to/codex.sock
```

`--endpoint` accepts `unix://`, `unix://PATH`, `ws://HOST:PORT`, or
`wss://HOST:PORT`. Bare `unix://` resolves to the same default control socket as
threadctl, under `CODEX_HOME` or `~/.codex`. `CODEX_GOALCTL_ENDPOINT` can supply
an explicit default. `--standalone` skips server discovery and overrides the
environment setting. It cannot be combined with `--endpoint`.

An explicit endpoint never falls back to a new process. Automatic selection
also stops on initialization, permission, timeout, or protocol errors rather
than hiding them with another server. Once a goal operation begins, goalctl
never switches transports or retries the write.

Use `--timeout` or `CODEX_GOALCTL_TIMEOUT` when app-server calls need more time.

## App-Server Methods

Goal operations use:

- `thread/goal/get`
- `thread/goal/set`
- `thread/goal/clear`

Automatic routing additionally uses `thread/loaded/list`. Goalctl does not
call spawn, send-input, wait, or transcript APIs.

## Thread IDs

The caller must already know the target thread id. For v1 Codex subagents, the
spawn result's `agent_id` is the thread id.

Some native subagent tools return a canonical task name such as
`/root/reviewer`. It is a tree-local routing handle rather than a goal
identifier. Resolve the task name through a tree-aware tool when available,
then retain the thread id for goal operations. Goalctl deliberately does not
depend on a shared app-server or resolve canonical task names itself.

The target must be reachable to the selected Codex instance. Standalone access
requires the same Codex home and a valid persisted thread id. Endpoint access
can also reach a thread loaded on that server. Goalctl does not load a thread or
move it between servers.

Current Codex permits goal reads on parent-owned v2 children but rejects
external goal changes. Their native parent workflow owns assignment and
lifecycle. When a host process or another thread needs direct goal control,
create an independent root through threadctl and retain its thread id. Resolving
a canonical task name or resuming a child does not transfer ownership.

## Live Accounting

Codex binds a running turn's accounting to a goal id. A goal write through the
server running that thread updates this binding as well as persisted state.
A separate server shares the database, not the worker's in-memory runtime.

Assigning or replacing a goal through a separate server during a turn can leave
that turn uncharged; the next turn picks up the new goal. An in-place budget
update preserves the goal id. Default routing avoids the separate-server gap
for workers on the usual shared server; select an explicit endpoint for workers
elsewhere. Reapplying `--status active` through the owning server binds an
already-running turn to its persisted goal without resetting counters.
Previously omitted usage is not recovered.

Standalone assignment before the first turn remains valid. It can also stage
a goal for a stopped worker whose execution must wait for a later event. Keep
assignment and starting work sequential on this path.

## Execution Boundary

On the owning server, setting an active goal may start or continue an idle
thread without another input. Arm any completion watcher before activation.
A goal response acknowledges the state change, not model execution. Standalone
writes do not directly start the worker on another server. A running worker
can still notice persisted goal changes at a later turn boundary.

When work still needs starting, use native control when a native subagent handle
is available. For an independent root, `codex-threadctl wake THREAD_ID --resume`
can continue from the assigned goal without adding user input, when immediate
thread control is available. Reapply any creation configuration file if cold
loading needs those overrides. Agent requests or corrections can use
`send --wake`; conditional or delayed delivery remains a separate scheduler
concern.
