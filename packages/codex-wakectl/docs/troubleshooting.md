# Troubleshooting

Use this when immediate input fails or a queued job remains pending.

## Pending Jobs

Check that a runner is processing the queue:

```sh
codex-wakectl run
codex-wakectl list
```

`run` exits nonzero for operational failures and records the newest error on
the pending job. Text output shows that error; `list --json` includes the full
condition and delivery state.

Confirm that the target is loaded on the same endpoint used by the job. When
`codex-threadctl` is installed, use:

```sh
codex-threadctl loaded
codex-threadctl status THREAD_ID
```

If the target is active, wakectl defers delivery unless the job was created with
`--allow-active`. Usually this is correct. Use that option only for input safe
to queue behind current work.

For goal predicates, verify that the goal exists and every predicate can match.
`--tokens-left-lte` cannot match a goal without a token budget. Repeating
buckets rebase without firing when a replacement goal or lower counters are
observed.

For stop predicates, create the job before the turn to observe. Use
`list --json` to inspect its stored turn cursor.

For command predicates, test that the command exits `0` from its stored cwd and
under the runner's environment. Interactive `PATH` and environment variables
may not exist under systemd.

## Duplicate Delivery

Duplicate wakes can occur when a runner delivers input but crashes before
recording success, when another runner retries an expired lease, or when the
condition was already handled manually.

Use `list --json` to identify stale or repeating jobs. Cancel only a job whose
id, target, condition, and message belong to the current workflow or an explicit
user instruction.
