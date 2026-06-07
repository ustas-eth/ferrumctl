# Troubleshooting

Use this when a wake did not arrive or a queued job keeps staying pending.

## Missed Wake Checklist

Check that the target thread is loaded on the endpoint you are using:

```sh
codex-wakectl loaded
codex-wakectl status THREAD_ID
```

If the app-server is not the default `unix://`, pass the same `--endpoint` used
when the sessions were started.

Check that a runner is processing the queue:

```sh
codex-wakectl run
codex-wakectl list
```

If the target is active, wakectl refuses the wake unless the job was created
with `--allow-active`. Usually this is the right behavior. Use `--allow-active`
for non-blocking reminders or corrections; wait for idle when the message is a
checkpoint.

If the target is idle but still has an active goal, it is wakeable and likely
needs a small message to observe or continue that goal. Inspect goal state
before changing direction.

For command predicates, verify the command exits `0` from the directory where
the job was created.

For goal predicates, verify the watched goal exists and that every predicate can
match. `--tokens-left-lte` cannot match a goal without a token budget.

For stop predicates, create the job before the turn you want to observe. A stop
job created after the thread already became idle waits for a future
active-to-idle edge.

## Duplicate Wake Checklist

Duplicate wakes are possible. Wake messages should be idempotent because
delivery is at-least-once.

Common causes:

- a runner sent the wake and crashed before recording the result
- multiple runners retried after a lease expired
- the user or another agent already handled the condition manually
- a repeating job was left active after the supervision loop ended

Use `codex-wakectl list` and `codex-wakectl cancel JOB_ID` to remove stale jobs.
