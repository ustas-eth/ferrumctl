<!-- Generated from packages/codex-wakectl/docs/troubleshooting.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Troubleshooting

Use this when a wake did not arrive or a queued job keeps staying pending.

## Missed Wake Checklist

Check that the target thread is loaded on the endpoint you are using:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
```

Use `codex-wakectl inspect THREAD_ID` when status alone does not explain whether
the thread is progressing, waiting, failed, or already finished.

If full inspection is slow or exceeds the app-server response limit, request
only the newest summary:

```sh
codex-wakectl inspect THREAD_ID --brief --no-previous
```

`--items N` shortens printed full output but does not reduce the full turn
transferred from the app-server.

If the app-server is not the default `unix://`, pass the same `--endpoint` used
when the sessions were started.

Check that a runner is processing the queue:

```sh
codex-wakectl run
codex-wakectl list
```

`run` exits nonzero for operational failures and records the newest error on the
pending job. Text `list` shows that error; use `list --json` for full history and
condition state.

If the target is active, wakectl refuses the wake unless the job was created
with `--allow-active`. Usually this is the right behavior. Use `--allow-active`
for non-blocking reminders or corrections; wait for idle when the message is a
checkpoint.

If the target is idle but still has an active goal, it is wakeable and likely
needs a small message to observe or continue that goal. Inspect goal state
before changing direction.

For command predicates, verify the command exits `0` from the directory where
the job was created and under the runner's environment. A predicate that works
in an interactive shell may have a different `PATH` under systemd.

For goal predicates, verify the watched goal exists and that every predicate can
match. `--tokens-left-lte` cannot match a goal without a token budget.
Repeating time/token buckets rebase without firing when a runner observes
a different goal creation time or lower counters.

For stop predicates, create the job before the turn you want to observe. The job
records the newest persisted turn as its cursor, so a turn completed before job
creation is not replayed. Use `list --json` to inspect the stored cursor.

## Duplicate Wake Checklist

Duplicate wakes are possible. Wake messages should be idempotent because
delivery is at-least-once.

Common causes:

- a runner sent the wake and crashed before recording the result
- multiple runners retried after a lease expired
- the user or another agent already handled the condition manually
- a repeating job was left active after the supervision loop ended

Use `codex-wakectl list --json` to inspect candidates, but cancel only jobs
whose id, target thread, condition, and message match your workflow or an
explicit user instruction.
