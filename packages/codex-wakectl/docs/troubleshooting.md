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

For an unqualified stop predicate, create the job before the turn to observe.
A pending reason such as `waiting for a later turn; cursor turn is completed`
means creation recorded an already-terminal boundary and no later completion
has appeared. If creation can race the intended completion, use `--turn
TURN_ID`; `--turn latest` deliberately binds the newest existing turn. Use
`list --json` to inspect the stored identity. A failed identity means
materialized history no longer contains it and the wake was not sent.

For command predicates, inspect `lastReason` as well as `lastError`. A reason
such as `command exited 1` only says that the predicate was not ready; wakectl
discards command output and cannot distinguish an expected false result from a
script defect.

Run the stored argv from its stored cwd and exercise both the ready and
not-ready cases when practical. Check permissions, interpreters, absolute
dependencies, and inputs that differ under the runner's environment;
interactive `PATH` and environment variables may not exist under systemd.
Predicates that need logs, mutable state, retries, or expensive calculation are
better split into a diagnostic watcher and a simple durable-state test.

For a long wait, inspect the job after its configured runner has evaluated it
once. Do not invoke `run` solely to test one job in the shared queue. A separate
time wake can provide a recovery turn if the condition remains false because
the watcher or predicate is wrong. It does not protect against the wakectl
runner itself being stopped.

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
