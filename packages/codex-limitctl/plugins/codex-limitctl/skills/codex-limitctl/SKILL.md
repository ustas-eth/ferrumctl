---
name: codex-limitctl
description: "Use when current Codex subscription capacity, daily account token activity, or local rollout-derived limit and thread activity history is needed, including a caller-supplied capacity gate. Do not use for per-thread context usage, goal budgets, API billing, exact account-to-thread attribution, paid credits, or reset consumption."
---

# Codex Limitctl

## Purpose

Use `codex-limitctl` to observe Codex subscription capacity and usage signals.
Current account reads use a short-lived stdio app-server; historical views use
local rollout files. The command is read-only and needs no persistent
app-server.

## Choose A View

- `list` reports current normalized rate-limit windows.
- `test` evaluates one caller-supplied remaining-capacity predicate.
- `usage` reports daily token activity for the current account.
- `history` reconstructs rate-limit observations from local rollouts.
- `activity` compares local token activity by thread, model, tier, and limit id.

Identify a window by backend limit id and duration, such as `codex` and `7d`:

```sh
codex-limitctl list
codex-limitctl list codex --window 7d
codex-limitctl test codex --window 7d --remaining-at-least 20
codex-limitctl usage --since 30d
codex-limitctl history codex --window 7d --since 30d
codex-limitctl activity --since 24h
```

Use `list` when no capacity policy has been supplied. Do not invent a threshold
for `test`.

## Interpret Results

`test` exits `0` when its predicate is true, `1` when false, and `2` when data
is unavailable or invalid. Preserve that third outcome rather than reporting
insufficient capacity.

Account capacity is shared and may change immediately after observation.
Missing windows are unknown, not fully available. A reset timestamp describes
ordinary window renewal, not a consumable account reset, and a percentage does
not reveal absolute tokens remaining.

`usage` is account-scoped. `history` and `activity` are reconstructed from this
host's rollouts and are not exact billing or account-to-thread attribution. A
thread on a history row recorded the snapshot; it did not necessarily cause the
account-level change. Goal token usage and thread context usage are separate
measurements.

Use `--json` when another program will parse an observation.

## References

- Read `references/limit-semantics.md` for window identity, normalization,
  missing data, freshness, exclusions, and exit status.
- Read `references/usage-history.md` for source scope, rollout reconstruction,
  concurrent snapshots, and token attribution.
- Read `references/coordination-principles.md` when composing capacity with
  goals, thread state, scheduled wakes, or native controls.
- Read `references/host-automation.md` for capacity gates, renewal wakes, and
  scripted or external management.
