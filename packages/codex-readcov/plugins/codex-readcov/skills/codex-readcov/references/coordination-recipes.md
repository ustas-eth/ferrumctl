<!-- Generated from docs/coordination-recipes.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coordination Recipes

These recipes show command combinations for common agent topologies. They are
examples, not required workflows.

For humans and scripts, use the installed commands directly. For Codex agents,
use recipes only for commands whose skills are available in the current context,
unless the user explicitly asks for a command or installs the missing skill.

Use real thread ids for placeholders such as `MAIN`, `WORKER`, `REVIEWER`,
`SELF`, and `NEXT`.

## Account Capacity Gate

Use `codex-limitctl` when a workflow has an explicit minimum-capacity policy. The
observation is account-wide and separate from goal budgets and thread context.

```sh
codex-limitctl list
codex-limitctl test codex --window 7d --remaining-at-least 20
```

When both the `codex-limitctl` and `codex-wakectl` skills are available and the
selected window reports a renewal time, a sleeping coordinator can wake then
re-evaluate the policy:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
RENEWS_AT=$(codex-limitctl list codex --window 7d --json |
  jq -r '.windows[0].resetsAt | todateiso8601')
codex-wakectl add time --at "$RENEWS_AT" --to "$SELF" \
  "Automated event: Subscription window renewed. Recheck the capacity policy."
```

An `add cmd` job can poll the same `test` predicate when readiness may change
before renewal, but each runner pass starts a short-lived app-server. Reserve
that form for short waits. Both false exit `1` and unavailable exit `2` remain
pending, so keep the inner timeout below the runner timeout and retain a separate
recovery path when observation failure must not wait indefinitely.

## Self-Managing Thread

Use `codex-wakectl` for self-wakes and `codex-threadctl` for host-visible state.
Use native goal tools for the current thread's goal when available;
`codex-goalctl` adds little for self-management.

Token-left predicates require the current goal to have a token budget. The
budget warning below uses `--allow-active` because it must reach the current
turn before the budget is exhausted.

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-threadctl status "$SELF"

codex-wakectl add time --after 30m \
  --to "$SELF" \
  "Self-scheduled reminder: Review progress and decide the next step."

codex-wakectl add goal "$SELF" --tokens-left-lte 300000 \
  --allow-active \
  --to "$SELF" \
  "Automated event: Goal budget is low. Summarize, stop, or request more budget."
```

Self read coverage is optional but useful for meta-review:

```sh
codex-readcov snapshot "$SELF" > self.before.json
# work happens here
codex-readcov delta self.before.json packages --limit 20
```

## Two Threads: Main Plus Worker

Main initializes work, worker runs, main reviews when the goal ends. The
full version uses the `codex-goalctl`, `codex-wakectl`, `codex-threadctl`, and
`codex-readcov` skills. If main has a native subagent handle, native input can
replace `codex-threadctl start` and native result retrieval can replace message
inspection. Native wait or poll can replace the wake watch only when main should
stay active and blocking is acceptable.

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=worker-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json

codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Automated event: Worker goal reached a terminal status. Inspect it."

codex-threadctl start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

When main is resumed:

```sh
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

If the inspected turn is still active, wait for it to end before relying on the
final response. Retrieve a native subagent response through its native handle;
for a standalone worker, use `codex-threadctl` or a shared result artifact.

If main should end its turn and return later, keep the `codex-wakectl add goal`
watch.

## Active Worker Supervision

Use this when a long-running worker has an active goal and the coordinator
should periodically decide whether to leave it alone, steer it, stop it, or
promote a result.

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=worker-thread-id

codex-threadctl inspect "$WORKER"
TURN=active-turn-id

codex-wakectl add goal "$WORKER" \
  --tokens-used-every 2000000 \
  --max-fires 4 \
  --to "$MAIN" \
  "Automated event: Worker token milestone. Reassess."
```

Use non-blocking steering when the worker may keep going:

```sh
codex-threadctl steer "$WORKER" "$TURN" \
  "From coordinator: Apply this ranking check to the next cycle and keep going."
```

If the coordinator has a native subagent input handle, use that handle for the
same immediate steering message. Keep `codex-wakectl` for milestone watches and
later resumption.

Use a checkpoint when the answer must gate continuation:

```sh
codex-threadctl inspect "$WORKER"
TURN=active-turn-id
codex-goalctl update "$WORKER" --status paused
codex-threadctl interrupt "$WORKER" "$TURN" --wait

codex-wakectl add stop "$WORKER" --to "$MAIN" \
  "Automated event: Worker answered checkpoint."
codex-threadctl start "$WORKER" \
  "From coordinator: Answer this checkpoint question briefly, update the relevant files if needed, and do not continue until resumed."

# after inspection
codex-threadctl inspect "$WORKER"
codex-goalctl update "$WORKER" --status active
codex-threadctl start "$WORKER" \
  "From coordinator: Resume the goal. Call get_goal and continue."
```

Pausing changes durable goal state; interruption is what stops the active turn.
If inspection already shows the worker idle, skip `interrupt`.

## Three Threads: Main, Worker, Reviewer

Main initializes. Worker does the task. Reviewer inspects the worker result and
wakes main only after review. This version uses the `codex-goalctl`,
`codex-wakectl`, `codex-threadctl`, and `codex-readcov` skills. Without
`codex-readcov`, the reviewer uses the result and thread history directly.
Without `codex-wakectl`, main must use native or manual input and wait paths.

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=worker-thread-id
REVIEWER=reviewer-thread-id
SNAPSHOT=$PWD/worker.before.json

codex-readcov snapshot "$WORKER" > "$SNAPSHOT"

codex-goalctl replace "$WORKER" \
  "Make the requested change and mark the goal complete."

codex-goalctl replace "$REVIEWER" \
  "On the completion event, review thread $WORKER and coverage since $SNAPSHOT. Report findings and mark this goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$REVIEWER" \
  "Automated event: Worker goal reached a terminal status. Inspect it and review from your goal."

codex-wakectl add goal "$REVIEWER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Automated event: Reviewer goal reached a terminal status. Inspect it."

codex-threadctl start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

The reviewer can inspect coverage before reporting:

```sh
WORKER=worker-thread-id-from-goal
SNAPSHOT=/absolute/path/from-goal
codex-goalctl get "$WORKER"
codex-threadctl inspect "$WORKER"
codex-readcov delta "$SNAPSHOT" packages --limit 20
```

When main wakes, it can retrieve the reviewer response through a native handle
or `codex-threadctl inspect "$REVIEWER"`.

## Standalone App-Server Sessions

Use this when the targets are normal Codex sessions loaded on a shared
app-server rather than native subagents of the current turn.
The `codex-threadctl` and `codex-wakectl` skills provide immediate control and
scheduled delivery; `codex-goalctl` and `codex-readcov` add durable state and
transcript evidence when available.

```sh
codex-threadctl loaded
codex-threadctl status "$WORKER"

codex-goalctl replace "$WORKER" \
  "Work from the persisted goal and mark it complete."

codex-wakectl add stop "$WORKER" \
  --to "$MAIN" \
  "Automated event: Worker turn ended. Inspect it."

codex-threadctl start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

Because the stop watch is created before `start`, it still observes a short
worker turn completed between runner passes.

`codex-goalctl` uses its own short-lived stdio app-server. It does not need to
use the same endpoint as `codex-wakectl`, but both must refer to the same Codex
home and thread id.

## Peer Handoff

One loaded session wakes another when a host-visible condition becomes true.
This requires the `codex-wakectl` skill. When `codex-goalctl` is available and
the next session needs a durable assignment, write it before arming the wake so
an already-true condition cannot arrive first.

```sh
NEXT=next-thread-id

codex-goalctl replace "$NEXT" \
  "Continue from done.txt, complete the next step, and mark this goal complete."

codex-wakectl add cmd --to "$NEXT" \
  "Automated event: Input is ready." \
  -- sh -c 'test -f done.txt'
```

Omit the goal write when only the `codex-wakectl` skill is available or the wake
message is deliberately the complete instruction.

## Coverage Audit And Gaps

Use `codex-readcov` to inspect transcript-recorded read actions during an
interval.

```sh
codex-readcov snapshot "$WORKER" > before.json
# work happens here
codex-readcov delta before.json packages --limit 20
```

Negative coverage is a normal set operation:

```sh
find packages -type f | sort > all.txt
codex-readcov delta before.json packages --paths-only --limit 0 | sort > read.txt
comm -23 all.txt read.txt
```

Compare several workers with plain path lists:

```sh
sort worker-*.read.txt | uniq -c | sort -nr
```

## External Host Manager

Another coding agent, such as Claude Code, can manage Codex sessions when it is
deliberately configured to use these host commands. It needs thread ids, the
same Codex home for persisted state and transcripts, and a shared app-server
endpoint for live wakes.

```sh
export CODEX_HOME=/path/to/codex-home
ENDPOINT=unix:///path/to/codex.sock
WORKER=worker-thread-id

codex-threadctl --endpoint "$ENDPOINT" loaded
codex-threadctl --endpoint "$ENDPOINT" inspect "$WORKER"
codex-readcov snapshot "$WORKER" > worker.before.json
codex-goalctl replace "$WORKER" "Work from this external assignment."
codex-threadctl --endpoint "$ENDPOINT" start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

This topology may need local conventions for thread discovery, socket paths,
and cleanup ownership.

## Short Catalog

- Sleeping coordinator: arm watches, stop the coordinating turn, wake it on
  goal status, turn completion, time, or command condition.
- Worker pool: one goal and optional read snapshot per worker; use
  `codex-wakectl`
  watches for attention, then retrieve each response through its native handle,
  `codex-threadctl`, or a shared artifact.
- Budget sentinel: use goal time/token predicates to wake the owner before
  budget exhaustion.
- Capacity gate: test an account rate-limit window before large fan-out, or use
  the same predicate as a durable wake condition.
- Script dispatcher: store snapshots, wake ids, and read lists as files; use
  `--json` for parsed state.
- Manual operator dashboard: combine `codex-threadctl loaded`, `status`, and
  `inspect` with `codex-goalctl get`, `codex-wakectl list`, and
  `codex-readcov top` or `delta`.
