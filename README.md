# codex-wakectl

`codex-wakectl` wakes Codex threads that are connected to a running
`codex app-server`.

It is a small local scheduler. It does not manage goals, parse transcripts, or
start Codex sessions. It sends an ordinary app-server `turn/start` input when a
condition becomes true.

## Install

```sh
uv tool install .
```

## App-Server Setup

Use a shared app-server and connect the Codex TUI to it:

```sh
codex app-server --listen unix://
codex --remote unix://
```

`codex-wakectl` defaults to the same `unix://` endpoint:

```sh
codex-wakectl loaded
```

Only loaded threads can be woken. If a thread is not loaded on the connected
app-server, `codex-wakectl` refuses to send the wake. This avoids writing to a
rollout behind a stale TUI.

## Immediate Wake

```sh
codex-wakectl send THREAD_ID "Check your goal and continue if useful."
```

By default, `send` refuses to start a new turn when the target thread is active.
Use `--allow-active` only when overlapping turns are intentional.

## Scheduled Wakes

Persist a wake job:

```sh
codex-wakectl add time --after 10m --to THREAD_ID "Wake up and check status."
codex-wakectl add time --at 2026-06-02T18:30:00Z --to THREAD_ID "Run the check."
```

Wake an orchestrator when another thread's goal changes state:

```sh
codex-wakectl add goal WORKER_THREAD_ID \
  --status complete,budgetLimited,usageLimited,blocked \
  --to ORCH_THREAD_ID \
  "The worker goal stopped. Inspect it and decide the next step."
```

Token predicates use plain integer token counts:

```sh
codex-wakectl add goal WORKER_THREAD_ID --tokens-left-lte 3000000 --to ORCH_THREAD_ID "Worker has <=3000000 tokens left."
codex-wakectl add goal WORKER_THREAD_ID --tokens-used-gte 3000000 --to ORCH_THREAD_ID "Worker has used 3000000 tokens."
codex-wakectl add goal WORKER_THREAD_ID --tokens-used-every 3000000 --to ORCH_THREAD_ID "Worker crossed another 3000000-token boundary."
```

Time-used predicates use duration units `s`, `m`, `h`, or `d`:

```sh
codex-wakectl add goal WORKER_THREAD_ID --time-used-gte 2h --to ORCH_THREAD_ID "Worker has run for 2h."
codex-wakectl add goal WORKER_THREAD_ID --time-used-every 30m --to ORCH_THREAD_ID "Worker crossed another 30m boundary."
```

Use command predicates for everything else. Exit status `0` means ready:

```sh
codex-wakectl add cmd --to THREAD_ID "The predicate is true." -- sh -c 'test -f done.txt'
```

For `cmd`, everything after `--` is the predicate command. Put
`codex-wakectl` options before that boundary.

Evaluate pending jobs from cron or a systemd timer:

```sh
codex-wakectl tick
```

Inspect and cancel jobs:

```sh
codex-wakectl list
codex-wakectl list --all
codex-wakectl cancel WAKE_ID
```

## Blocking Conditions

`wait` checks the same condition syntax without creating a job:

```sh
codex-wakectl wait time --after 5m
codex-wakectl wait goal THREAD_ID --status complete --poll-interval 15
codex-wakectl wait cmd -- sh -c 'git diff --quiet'
```

This is useful in shell scripts:

```sh
codex-wakectl wait goal WORKER_THREAD_ID --status complete && \
  codex-wakectl send ORCH_THREAD_ID "Worker is complete. Inspect the result."
```

## State

Jobs are stored in:

```text
$XDG_STATE_HOME/codex-wakectl/jobs.json
```

or, when `XDG_STATE_HOME` is unset:

```text
~/.local/state/codex-wakectl/jobs.json
```

Override with `--state PATH`.

## Scope

`codex-wakectl` is for app-server-backed sessions. It is not a terminal input
injector and does not wake ordinary embedded TUI sessions.

The app-server interface is experimental. Keep the endpoint explicit, keep wake
messages idempotent, and prefer `tick` from cron/systemd over a long-running
custom daemon.
