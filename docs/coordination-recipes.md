# Coordination Recipes

These recipes show command combinations for common agent topologies. They are
examples, not required workflows.

For humans and scripts, use the installed commands directly. For Codex agents,
use recipes only for commands whose skills are available in the current context,
unless the user explicitly asks for a command or installs the missing skill.

Use real thread ids for placeholders such as `MAIN`, `WORKER`, `REVIEWER`,
`SELF`, and `NEXT`.

## Self-Managing Thread

Use `wakectl` for self-wakes. Use native goal tools for the current thread's
goal when available; `goalctl` adds little for self-management.

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
codex-wakectl status "$SELF"

codex-wakectl add time --after 30m \
  --to "$SELF" \
  "Time check. Review progress and decide the next step."

codex-wakectl add goal "$SELF" --tokens-left-lte 300000 \
  --to "$SELF" \
  "Budget is low. Summarize, stop, or request more budget."
```

Self read coverage is optional but useful for meta-review:

```sh
codex-readcov snapshot "$SELF" > self.before.json
# work happens here
codex-readcov delta self.before.json packages --limit 20
```

## Two Threads: Main Plus Worker

Main initializes work, worker runs, main reviews when the worker stops. The
full version uses the `goalctl`, `wakectl`, and `readcov` skills; omit commands
for unavailable skills or replace wake/watch commands with native subagent input
and wait.

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=worker-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json

codex-goalctl replace "$WORKER" \
  "Review this package and mark the goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Worker goal stopped. Inspect goal state and read coverage."

codex-wakectl send "$WORKER" \
  "A goal was assigned. Call get_goal and proceed."
```

When main is resumed:

```sh
codex-goalctl get "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

If main has a native subagent handle and should stay active, native wait or poll
can replace the `wakectl add goal` watch.

## Three Threads: Main, Worker, Reviewer

Main initializes. Worker does the task. Reviewer inspects the worker result and
wakes main only after review. The full version uses all three skills. Without
`readcov`, the reviewer inspects the result directly. Without `wakectl`, main
must use native or manual input and wait paths.

```sh
MAIN=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
WORKER=worker-thread-id
REVIEWER=reviewer-thread-id

codex-readcov snapshot "$WORKER" > worker.before.json

codex-goalctl replace "$WORKER" \
  "Make the requested change and mark the goal complete."

codex-goalctl replace "$REVIEWER" \
  "Wait for the worker wake. Review the worker result and read coverage, then mark this goal complete."

codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$REVIEWER" \
  "Worker stopped. Review WORKER=$WORKER and worker.before.json, then update your goal."

codex-wakectl add goal "$REVIEWER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$MAIN" \
  "Reviewer stopped. Inspect the review result."

codex-wakectl send "$WORKER" \
  "A goal was assigned. Call get_goal and proceed."
```

The reviewer can inspect coverage before reporting:

```sh
codex-goalctl get "$WORKER"
codex-readcov delta worker.before.json packages --limit 20
```

## Standalone App-Server Sessions

Use this when the targets are normal Codex sessions loaded on a shared
app-server rather than native subagents of the current turn.
The `wakectl` skill is the key surface for this topology; `goalctl` and
`readcov` add durable state and transcript evidence when available.

```sh
codex-wakectl loaded
codex-wakectl status "$WORKER"

codex-goalctl replace "$WORKER" \
  "Work from the persisted goal and mark it complete."

codex-wakectl add stop "$WORKER" \
  --to "$MAIN" \
  "Worker stopped. Inspect it."

codex-wakectl send "$WORKER" \
  "A goal was assigned. Call get_goal and proceed."
```

`goalctl` uses its own short-lived stdio app-server. It does not need to use the
same endpoint as `wakectl`, but both must refer to the same Codex home and
thread id.

## Peer Handoff

One loaded session wakes another when a host-visible condition becomes true.
This requires the `wakectl` skill. Add `goalctl` only when the next session
needs durable instructions beyond the wake message.

```sh
NEXT=next-thread-id

codex-wakectl add cmd --to "$NEXT" \
  "Input is ready. Inspect done.txt and continue." \
  -- sh -c 'test -f done.txt'
```

Add a persisted goal when the next session should have durable instructions:

```sh
codex-goalctl replace "$NEXT" \
  "Continue from done.txt, complete the next step, and mark this goal complete."
```

## Coverage Audit And Gaps

Use `readcov` to inspect what a worker actually read during an interval.

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

codex-wakectl --endpoint "$ENDPOINT" loaded
codex-goalctl replace "$WORKER" "Work from this external assignment."
codex-wakectl --endpoint "$ENDPOINT" send "$WORKER" \
  "A goal was assigned. Call get_goal and proceed."
codex-readcov snapshot "$WORKER" > worker.before.json
```

This topology may need local conventions for thread discovery, socket paths,
and cleanup ownership.

## Short Catalog

- Sleeping coordinator: arm watches, stop the coordinating turn, wake it on
  goal status, stop edge, time, or command condition.
- Worker pool: one goal and optional read snapshot per worker; collect results
  with `goalctl get`, `wakectl` watches, and `readcov` path lists.
- Budget sentinel: use goal time/token predicates to wake the owner before
  budget exhaustion.
- Script dispatcher: store snapshots, wake ids, and read lists as files; use
  `--json` for parsed state.
- Manual operator dashboard: run `loaded`, `status`, `get`, `list`, `top`, and
  `delta` ad hoc to inspect live, goal, queue, and transcript state.
