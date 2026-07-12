# codex-threadctl

`codex-threadctl` discovers, inspects, and controls Codex threads through a shared
`codex app-server`.

Use it to find or search stored sessions and spawned threads, inspect recent
work, retrieve conversation messages, inspect running terminal processes,
start or steer input, resume a persisted thread, or interrupt one known turn.
It does not edit goals, schedule future work, or measure file-read coverage.

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

Find recently used sessions or threads spawned by a known parent:

```sh
codex-threadctl list --limit 10
codex-threadctl list --parent THREAD_ID --sort created --limit 5
codex-threadctl list --ancestor THREAD_ID
codex-threadctl search "decision text" --limit 10
```

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

Start a new turn on an idle thread, or steer one known active turn:

```sh
codex-threadctl start THREAD_ID "Check your goal and continue."
codex-threadctl steer THREAD_ID TURN_ID "Focus on the failing test first."
```

Resume a stored thread or request interruption of one exact turn:

```sh
codex-threadctl resume THREAD_ID --continue-goal
codex-threadctl interrupt THREAD_ID TURN_ID --wait
```

Resume does not add a user message. Because Codex can continue an active goal
after resume and app-server cannot exclude that behavior atomically, every
resume requires `--continue-goal` as an explicit acknowledgement.

List running terminal processes or terminate one exact process:

```sh
codex-threadctl terminals THREAD_ID
codex-threadctl terminate-terminal THREAD_ID PROCESS_ID --item ITEM_ID
```

Use the process and item ids from the same current `terminals` listing.

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
