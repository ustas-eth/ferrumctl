---
name: codex-limitctl
description: "Use when you need the host codex-limitctl command to inspect current Codex subscription rate-limit windows or gate work on remaining account capacity. Do not use for per-thread context usage, goal token budgets, API billing, historical usage analytics, paid or reset credits, or reset consumption."
---

# Codex Limitctl

## Purpose

Use this skill when this session needs to observe account-wide Codex
subscription capacity from the host or apply an existing capacity policy in a
script.

Assume `codex-limitctl` is installed. It reads rate-limit windows through a
short-lived stdio app-server and requires no persistent app-server. It is
read-only and does not expose account analytics, credits, or consumable resets.

## Model

- `list` reports normalized rate-limit windows.
- `test` evaluates one remaining-capacity predicate through its exit status.
- A window is selected by backend limit id and duration, such as `codex` and
  `7d`.
- Account capacity is shared across threads and can change after any
  observation.
- Goal token usage and thread context usage are different measurements.

## Patterns

List current observations before choosing work:

```sh
codex-limitctl list
codex-limitctl list codex --window 7d
```

Apply a supplied threshold and preserve its three-way result:

```sh
codex-limitctl test codex --window 7d --remaining-at-least 20
status=$?
case "$status" in
  0) printf 'capacity available\n' ;;
  1) printf 'capacity below threshold\n' ;;
  *) exit "$status" ;;
esac
```

Match a low-capacity condition:

```sh
codex-limitctl test codex --window 5h --remaining-at-most 10
```

Use `--json` when another command needs the observation itself:

```sh
codex-limitctl list codex --window 7d --json
codex-limitctl test codex --window 7d --remaining-at-least 20 --json
```

## Conventions

- Use `list` when no capacity policy has been supplied. Do not invent a
  threshold on the user's behalf.
- Treat `test` exit `0` as true, `1` as false, and `2` as unavailable or
  invalid data. Do not collapse exit `2` into a claim of insufficient capacity.
- Identify windows by duration, not by assumptions about `primary` and
  `secondary` backend positions.
- Treat an omitted window as unknown, not as fully available.
- Treat the reported reset timestamp as ordinary window renewal, not a
  consumable account reset.
- Do not infer absolute tokens remaining from the reported percentage.

## References

- Read `references/limit-semantics.md` when window identity, normalization,
  missing data, freshness, exclusions, or exit status matters.
- Read `references/coordination-principles.md` when composing account capacity
  with goals, thread state, scheduled wakes, or native controls.
- Read `references/coordination-recipes.md` for capacity gates in a larger
  agent workflow.
- Read `references/operational-caveats.md` when a stale observation, concurrent
  account use, or a durable command predicate could affect correctness.
