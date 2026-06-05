# Wake Scheduling

`codex-wakectl` sends normal app-server turns to loaded Codex threads. It is not
a terminal input injector and cannot wake sessions that are not connected to the
selected app-server.

## Conditions

Immediate wake:

```sh
codex-wakectl send THREAD_ID "Check status and continue if useful."
```

Time condition:

```sh
codex-wakectl add time --after 10m --to THREAD_ID "Wake up and check status."
```

Goal condition:

```sh
codex-wakectl add goal WORKER \
  --status complete,blocked,budgetLimited,usageLimited \
  --to ORCH \
  "Worker goal stopped. Inspect it."
```

Stop condition:

```sh
codex-wakectl add stop WORKER --to ORCH "Worker stopped. Inspect it."
```

`stop` is an active-to-idle edge. If the thread is already idle when the job is
created, the job waits until the thread is observed active and then idle again.
Create a stop watch before starting the turn it should observe.

Command condition:

```sh
codex-wakectl add cmd --to THREAD_ID "Predicate is true." -- sh -c 'test -f done.txt'
```

The command runs from the directory where the job was created. The wakectl
timeout also bounds the predicate command.

## Repeating Wakes

Goal milestone predicates repeat by default:

```sh
codex-wakectl add goal WORKER --tokens-used-every 3000000 --to ORCH "Token milestone."
codex-wakectl add goal WORKER --time-used-every 30m --to ORCH "Time milestone."
```

They fire once per crossed bucket. The current bucket is seeded at job creation,
so old milestones do not fire immediately.

Stop notifications repeat only with `--repeat`:

```sh
codex-wakectl add stop WORKER --repeat --to ORCH "Worker completed another turn."
```

Use `--max-fires N` when a repeating job should stop by itself:

```sh
codex-wakectl add stop WORKER --repeat --max-fires 5 --to ORCH "Worker completed another turn."
```

## Concurrency

Queued wakes are polling-backed notifications. They may run late, retry after a
failed send, or become redundant if the orchestrator already handled the result.

By default, `send` and queued wakes refuse to start a turn while the target
thread is active. Use `--allow-active` only when overlapping turns are
intentional.

Keep wake messages idempotent and cancel stale jobs when the supervision loop is
over.

## State

Wake jobs are stored in SQLite under:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.sqlite3
```

or `~/.local/state/codex-wakectl/jobs.sqlite3` when `XDG_STATE_HOME` is unset.
Override with `--state PATH`.

`codex-wakectl run` claims pending jobs before evaluating them. Claims expire so
another runner can retry after a crashed process.
