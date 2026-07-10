<!-- Generated from packages/codex-wakectl/docs/troubleshooting.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Troubleshooting

Use this when a queued job remains pending, fails, or has an uncertain outcome.

## Pending Jobs

Check that a runner is processing the queue:

```sh
codex-wakectl run
codex-wakectl list
```

`run` exits nonzero for operational failures and records the newest error on
the pending job. Text output shows that error; `list --json` includes the full
condition and delivery state.

Confirm that the target is loaded on the same endpoint used by the job.
`codex-threadctl` exposes that state through:

```sh
codex-threadctl loaded
codex-threadctl status THREAD_ID
```

If the target is active, wakectl defers delivery unless the job was created with
`--allow-active`. That option uses expected-turn steering and remains suitable
only for input valid during current work.

For goal predicates, verify that the goal exists and every predicate can match.
`--tokens-left-lte` cannot match a goal without a token budget. Lower counters
rebase repeating buckets; a replacement assignment makes the job
`superseded`.

For stop predicates, create the job before the turn to observe. Use
`list --json` to inspect its stored turn cursor. A `failed` cursor means that
materialized history no longer contains the boundary and the wake was not sent.

For command predicates, test that the command exits `0` from its stored cwd and
under the runner's environment. Interactive `PATH` and environment variables
may not exist under systemd.

An `uncertain` job submitted native start or steer input but could not confirm
the outcome. It is not retried automatically. Inspect the target and compare
`lastClientMessageId` with structured threadctl message output before deciding
whether another message is appropriate.

## Duplicate Delivery

Duplicate wakes can occur when a runner delivers input but crashes before
recording success, when another runner retries an expired lease, or when the
condition was already handled manually.

Use `list --json` to identify stale or repeating jobs. Cancel only a job whose
id, target, condition, and message belong to the current workflow or an explicit
user instruction.
