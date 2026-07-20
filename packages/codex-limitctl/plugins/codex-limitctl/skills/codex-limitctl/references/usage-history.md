<!-- Generated from packages/codex-limitctl/docs/usage-history.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Usage History

`codex-limitctl` exposes two different historical views. Their sources and
scope are intentionally kept separate.

## Account Activity

`usage` reads `account/usage/read` through a short-lived Codex app-server. It
returns the daily token buckets reported for the current Codex login and omits
the backend summary and credit fields.

`--since` filters reported dates. The command does not fill missing dates or
estimate the current day, which may still be incomplete when observed.

## Local Rollouts

`history` and `activity` scan rollout JSONL files under `sessions` and
`archived_sessions` in `CODEX_HOME`. A file is selected by modification time,
then its records are filtered by timestamp. This includes a long-running thread
whose rollout remains in an older date directory.

Rollouts do not identify the ChatGPT account that produced them. These commands
therefore report host-local, account-unscoped observations. Files retained from
different logins can appear together.

An active rollout may end with an incomplete JSON line. The scanner ignores
malformed records so one partial write does not invalidate the rest of the
observation.

## Rate-Limit History

`history` extracts rate-limit snapshots recorded with token updates. It groups
windows by limit id and duration, normalizes small historical drift around the
5-hour and 7-day durations, and removes repeated snapshots.

The reported thread, model, and service tier identify the rollout that recorded
an observation. They do not identify which thread caused an account-level
change.

Concurrent threads can record stale account state. Within one reset boundary,
the reducer accepts increasing usage and ignores lower values. A meaningfully
later reset timestamp starts a new boundary; an older one is ignored. This
keeps common stale snapshots out, but cannot prove why capacity changed and can
miss a real decrease whose reset boundary did not move.

## Thread Activity

`activity` calculates positive deltas from each rollout's cumulative token
counters and groups them by thread, model, service tier, and reported limit id.
Repeated counters are ignored. An inherited counter at the start of a fork is
used as a baseline rather than attributed to the new thread. A counter decrease
starts a new baseline.

Input, output, cached input, and reasoning output are reported separately.
Cached input is part of input, and reasoning output is part of output; these
fields must not be added to `totalTokens`.

Local activity is a workload signal, not account consumption attribution.
Rate-limit percentages are shared, quantized, and affected by model and service
tier. Local totals may differ from daily account buckets and must not be
converted into percentage use or tokens remaining.
