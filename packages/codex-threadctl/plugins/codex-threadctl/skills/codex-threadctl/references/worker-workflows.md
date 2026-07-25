<!-- Generated from docs/worker-workflows.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Worker Workflows

These examples combine ferrumctl commands for self-managed threads,
coordinator-worker runs, and reviewer chains. Each package is optional. In an
agent session, use only commands whose skills are available unless the user
explicitly requests another installed command.

When the coordinator owns a native subagent handle, prefer native input, wait,
and result retrieval. The thread-id commands below are useful for standalone
sessions, host control, or persisted state beyond the native result.

## Self-Managed Thread

Use native goal tools for the current thread when available. A self-wake is
useful only when the current turn can end while later attention remains
scheduled:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}

codex-wakectl add time --after 30m --to "$SELF" \
  "Self-scheduled reminder: Review progress."
```

A goal-budget event requires the current goal to have a token budget. It can
reach an active turn when the warning remains valid during current work:

```sh
codex-wakectl add goal "$SELF" --tokens-left-lte 300000 \
  --allow-active --to "$SELF" \
  "Automated event: Goal budget is low."
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
WORKER=worker-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json

codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Automated event: Worker goal reached a terminal status."

codex-threadctl start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

Omit layers that are not needed. A native subagent message can replace
`threadctl start`; native waiting can replace the wake only when the
coordinator should remain active; coverage is optional.

After the event, inspect each relevant state separately:

```sh
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

A terminal goal can precede the final response. Retrieve the native result or
observe the worker's turn boundary when that response matters.

## Ongoing Supervision

Repeating milestones can return a coordinator to a long-running worker without
holding the coordinating turn open:

```sh
codex-wakectl add goal "$WORKER" \
  --tokens-used-every 2000000 \
  --max-fires 4 \
  --to "$MAIN" \
  "Automated event: Worker token milestone."
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

codex-wakectl add stop "$WORKER" --to "$MAIN" \
  "Automated event: Worker answered the checkpoint."
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

A reviewer can become the recipient of the worker's completion event, with the
coordinator notified only after review:

```sh
REVIEWER=reviewer-thread-id
SNAPSHOT=$PWD/worker.before.json

codex-goalctl replace "$REVIEWER" \
  "Review thread $WORKER and coverage since $SNAPSHOT, report findings, and mark this goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$REVIEWER" \
  "Automated event: Worker goal reached a terminal status."

codex-wakectl add goal "$REVIEWER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Automated event: Reviewer goal reached a terminal status."
```

The reviewer can inspect the worker through its thread id and read snapshot,
then leave its result in its own final response. Main retrieves that response
through the native handle or retained thread history.

## Standalone Sessions

For normal Codex sessions rather than native subagents, load the participants
on one shared app-server and use their thread ids:

```sh
codex-threadctl loaded
codex-threadctl status "$WORKER"
```

`codex-goalctl` uses its own short-lived stdio app-server, so it need not share
the live endpoint. It must still use the same Codex home and thread identity.
