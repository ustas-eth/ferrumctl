# Worker Workflows

These examples combine ferrumctl commands for self-managed threads,
coordinator-worker runs, and reviewer chains. Each package is optional. In an
agent session, use only commands whose skills are available unless the user
explicitly requests another installed command.

When the coordinator owns a native subagent handle, prefer native input, wait,
and result retrieval. Use an independent root when direct thread-id control must
remain available to another thread or host process.

## Self-Managed Thread

Use native goal tools for the current thread when available. A self-wake is
useful only when the current turn can end while later attention remains
scheduled:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}

codex-wakectl add time --after 30m --to "$SELF"
```

A goal-budget event requires the current goal to have a token budget. It can
reach an active turn when the warning remains valid during current work:

```sh
codex-wakectl add goal "$SELF" --tokens-left-lte 300000 \
  --notify-active --to "$SELF"
```

## Coordinator And Worker

Arm the coordinator's later attention before activating the worker's goal:

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=$(codex-threadctl create --cwd "$PWD")

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN"

codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete." --token-budget 500000
```

Omit layers that are not needed. `create` makes a persisted root with no native
parent or automatic result return. A native subagent remains simpler when the
current session should own the worker and direct external control is
unnecessary. Native waiting can replace the wake only when the coordinator
should remain active.

The budget here is an example, not a default. Choose it for the assignment;
omitting a budget leaves the goal unbounded. Goalctl automatically uses the
default server when it holds the worker. Setting an active goal there may start
work immediately. If inspection shows that work still needs starting, use
`codex-threadctl wake "$WORKER" --resume`. If creation used a configuration
file, also pass `--config-file FILE` on cold loading; a loaded worker keeps its
settings. A watcher can be registered before a goal exists.

Later edits use the same automatic routing:

```sh
codex-goalctl update "$WORKER" --token-budget 750000
```

After the event, inspect each relevant state separately:

```sh
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
```

A terminal goal can precede the final response. Retrieve the native result or
observe the worker's turn boundary when that response matters.

## Native Agent Tree

Some native subagent tools identify each member by a canonical task name such as
`/root/reviewer`. Use threadctl to inspect the mapping, then keep the resolved
thread id for read-only operations and condition subjects that require one:

```sh
codex-threadctl agents
WORKER=$(codex-threadctl resolve /root/reviewer)
codex-goalctl get "$WORKER"
```

A scheduled condition can use canonical task names directly and return
attention to the root:

```sh
codex-wakectl add goal /root/reviewer \
  --status complete,blocked,budgetLimited,usageLimited \
  --to /root
```

Start, continue, and assign the child through its native parent workflow.
Current Codex rejects direct external input, context injection, and goal changes
to parent-owned v2 children. Canonical task names remain valid observation
handles, but do not transfer ownership. Use an independent root instead when
direct ferrumctl control is required. Outside the tree, add `--tree THREAD_ID`
when resolving a task name.

## Ongoing Supervision

Repeating milestones can return a coordinator to a long-running worker without
holding the coordinating turn open:

```sh
codex-wakectl add goal "$WORKER" \
  --tokens-used-every 2000000 \
  --max-fires 4 \
  --to "$MAIN"
```

Inspect before deciding whether intervention is useful. An agent correction
can enter current context without pretending to be user input:

```sh
codex-threadctl inspect "$WORKER"
codex-threadctl send "$WORKER" \
  "Apply this constraint to the next cycle and continue."
```

When a checkpoint must stop automatic continuation, goal status and turn
execution must both be controlled:

```sh
codex-goalctl update "$WORKER" --status paused
codex-threadctl interrupt "$WORKER" ACTIVE_TURN_ID --wait

codex-wakectl add stop "$WORKER" --to "$MAIN"
codex-threadctl send "$WORKER" \
  "Answer this checkpoint and stop: QUESTION" --wake
```

After reviewing the response, reactivate the assignment:

```sh
codex-goalctl update "$WORKER" --status active
```

Skip interruption when current inspection already shows the worker idle.
If reactivation does not start work, `wake --resume` can continue from the goal.

## Worker And Reviewer

To insert a reviewer, create the worker but defer its goal assignment. Replace
the direct worker-to-coordinator watch with this chain, then activate the worker
as above:

```sh
REVIEWER=$(codex-threadctl create --cwd "$PWD")

codex-goalctl replace "$REVIEWER" \
  "Review thread $WORKER and its changes, report findings, and mark this goal complete." \
  --standalone

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$REVIEWER"

codex-wakectl add goal "$REVIEWER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN"
```

Here `--standalone` stages a goal for the stopped reviewer without starting it;
the worker's eventual event restores its attention. The reviewer can inspect
the worker through its thread id and examine its work, then leave its result
in its own final response. Main retrieves that response
through the native handle or retained thread history.

## Standalone Sessions

Create externally controlled participants as independent roots on one shared
app-server and retain their thread ids:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project)
codex-threadctl loaded
codex-threadctl status "$WORKER"
```

`codex-goalctl` reuses the default server when it holds the worker. For a worker
on another server, select the same `--endpoint` for goal changes.
