# codex-limitctl

`codex-limitctl` reads Codex subscription limits and usage signals.

Use it to check current capacity, list daily account token activity, follow
rate-limit changes, or compare token activity across local Codex threads.

Current account data comes from a short-lived stdio app-server. Historical
thread data comes from local Codex rollout files. No shared server or collector
is required.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-limitctl
```

From this package directory:

```sh
uv tool install .
```

## Examples

List all reported windows, or select one by limit id and duration:

```sh
codex-limitctl list
codex-limitctl list codex --window 7d
```

Test remaining capacity through the exit status:

```sh
codex-limitctl test codex --window 7d --remaining-at-least 20
codex-limitctl test codex --window 5h --remaining-at-most 10
```

`test` exits `0` when the predicate matches, `1` when it does not, and `2` when
the requested window or account observation is unavailable. It is quiet unless
`--json` is used.

```sh
codex-limitctl list --json
```

See daily account activity and local history:

```sh
codex-limitctl usage --since 30d
codex-limitctl history codex --window 7d --since 30d
codex-limitctl activity --since 24h | head
```

`history` and `activity` describe this host's rollout files. They are useful for
trends, but are not billing records or exact account-to-thread attribution.

More detail:

- [docs/limit-semantics.md](docs/limit-semantics.md)
- [docs/usage-history.md](docs/usage-history.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-limitctl@ferrumctl
```

The skill lives at `plugins/codex-limitctl/skills/codex-limitctl/SKILL.md`.
