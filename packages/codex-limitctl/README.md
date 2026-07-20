# codex-limitctl

`codex-limitctl` reads Codex subscription rate-limit windows.

Use it when a script or agent needs machine-readable 5-hour, weekly, or other
reported capacity. It does not expose historical account usage, paid credits,
reset credits, or reset consumption.

Each command starts a short-lived stdio app-server, so no shared server is
required.

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

More detail:

- [docs/limit-semantics.md](docs/limit-semantics.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-limitctl@ferrumctl
```

The skill lives at `plugins/codex-limitctl/skills/codex-limitctl/SKILL.md`.
