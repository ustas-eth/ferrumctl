# Limit Semantics

`codex-limitctl` reads `account/rateLimits/read` through a short-lived Codex
app-server. The command uses the current Codex login and does not require a
persistent app-server or an app-server-backed thread.

`--timeout` bounds app-server startup, initialization, and the account read as
one observation. Failure output omits raw app-server responses and diagnostics.

## Window Identity

The backend reports snapshots by limit id. A limit id identifies a metered
bucket and is not necessarily a model name. Its optional display name provides
additional context when available.

Each normalized row is identified by its limit id and window duration. The
backend's `primary` and `secondary` field positions are not treated as stable
semantics; their order can change. Conflicting rows for the same limit id and
duration are rejected.

`usedPercent` is reported by Codex. `remainingPercent` is derived as
`100 - usedPercent`. No absolute token allowance can be inferred from these
percentages.

`resetsAt` is the normal renewal time for the reported window. It does not
represent or expose a consumable reset.

## Missing Data

A missing duration is retained as `unknown` in an unfiltered listing. It cannot
match an exact `--window` filter.

An omitted requested window is unavailable, not implicitly unused. `list`
reports that as an error. `test` distinguishes an unavailable observation from
a false predicate through exit status `2`.

## Scope And Freshness

Rate-limit state belongs to the Codex account and is shared by its threads.
Every invocation is a point-in-time observation; concurrent work can change the
next result immediately.

The JSON output is built from normalized window fields. Backend fields for
historical token analytics, paid credits, spending controls, and reset credits
are not returned.

## Exit Status

- `list`: `0` for reported rows and `2` for unavailable or invalid data.
- `test`: `0` when true, `1` when false, and `2` when the predicate could not be
  evaluated.

Transport, authentication, timeout, and schema errors also exit `2`.
