# codex-threadctl

`codex-threadctl` inspects and controls Codex threads through a shared
`codex app-server`.

Use it to check thread activity, inspect recent work and context usage, retrieve
conversation messages, interrupt a turn, or request compaction. It does not
send input, edit goals, or measure file-read coverage.

It is also the home of the observation and lifecycle commands moved out of
`codex-wakectl` 0.3.

## Install

From the `ferrumctl` root:

```sh
uv tool install ./packages/codex-threadctl
```

From this package directory:

```sh
uv tool install .
```

## Setup

Run one app-server, then start or resume Codex sessions through it:

```sh
codex app-server --listen unix://
codex --remote unix://
codex-threadctl loaded
```

## Examples

Inspect the current state and recent activity of a thread:

```sh
codex-threadctl inspect THREAD_ID
codex-threadctl inspect THREAD_ID --brief
```

List recent conversation messages, then print one in full:

```sh
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

The list output includes both ids because an item id is only unique within its
turn.

Interrupt active work or compact an idle thread with no active goal:

```sh
codex-threadctl interrupt THREAD_ID
codex-threadctl compact THREAD_ID
```

Use `--json` when another program will parse output.

More detail:

- [docs/observation-semantics.md](docs/observation-semantics.md)
- [docs/lifecycle-control.md](docs/lifecycle-control.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-threadctl@ferrumctl
```

The skill lives at `plugins/codex-threadctl/skills/codex-threadctl/SKILL.md`.
