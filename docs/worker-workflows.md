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

Read coverage can provide a separate view of one work interval:

```sh
codex-readcov snapshot "$SELF" > self.before.json
# work happens here
codex-readcov delta self.before.json packages --limit 20
```

## Coordinator And Worker

The full sequence assigns durable work, arranges the coordinator's later
attention, and then starts the worker:

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=$(codex-threadctl create --cwd "$PWD")

codex-readcov snapshot "$WORKER" > worker.before.json

codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN"

codex-threadctl start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

Omit layers that are not needed. `create` makes a persisted root with no native
parent or automatic result return. A native subagent remains simpler when the
current session should own the worker and direct external control is
unnecessary. Native waiting can replace the wake only when the coordinator
should remain active; coverage is optional.

After the event, inspect each relevant state separately:

```sh
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
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

Inspect before deciding whether intervention is useful. A non-blocking
correction can use the currently observed turn id:

```sh
codex-threadctl inspect "$WORKER"
codex-threadctl steer "$WORKER" ACTIVE_TURN_ID \
  "From coordinator: Apply this constraint to the next cycle and continue."
```

When a checkpoint must stop automatic continuation, goal status and turn
execution must both be controlled:

```sh
codex-goalctl update "$WORKER" --status paused
codex-threadctl interrupt "$WORKER" ACTIVE_TURN_ID --wait

codex-wakectl add stop "$WORKER" --to "$MAIN"
codex-threadctl start "$WORKER" \
  "From coordinator: Answer this checkpoint and stop: QUESTION"
```

After reviewing the response, reactivate the assignment and direct the worker
back to its durable goal:

```sh
codex-goalctl update "$WORKER" --status active
codex-threadctl start "$WORKER" \
  "From coordinator: Call get_goal and continue."
```

Skip interruption when current inspection already shows the worker idle.

## Worker And Reviewer

To insert a reviewer into the earlier sequence, omit its direct
worker-to-coordinator wake. Keep the worker assignment and read snapshot, then
arm the worker-to-reviewer and reviewer-to-coordinator wakes instead:

```sh
REVIEWER=reviewer-thread-id
SNAPSHOT=$PWD/worker.before.json

codex-goalctl replace "$REVIEWER" \
  "Review thread $WORKER and coverage since $SNAPSHOT, report findings, and mark this goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$REVIEWER"

codex-wakectl add goal "$REVIEWER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN"
```

The reviewer can inspect the worker through its thread id and read snapshot,
then leave its result in its own final response. Main retrieves that response
through the native handle or retained thread history.

## Standalone Sessions

Create externally controlled participants as independent roots on one shared
app-server and retain their thread ids:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project)
codex-threadctl loaded
codex-threadctl status "$WORKER"
```

`codex-goalctl` uses its own short-lived stdio app-server, so it need not share
the live endpoint. It must still use the same Codex home and thread identity.
