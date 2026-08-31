# codex-threadctl

`codex-threadctl` creates, discovers, inspects, and controls Codex threads
through a shared `codex app-server`.

Use it to create an independently controlled worker, find stored sessions and
spawned threads, inspect recent work and retained messages, or apply immediate
control through a thread id or canonical task name such as `/root/reviewer`.
It does not edit goals, schedule future input, or measure file-read coverage.

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

Create a persisted root worker for direct control by another thread or host
process:

```sh
WORKER=$(codex-threadctl create --cwd "$PWD")
codex-threadctl start "$WORKER" \
  "From coordinator: Begin the assigned work."
```

The command prints only the new thread id and does not start a turn. It writes a
short `threadctl` advisory item so the thread is persisted before its first
turn. The worker is independent: it has no native parent handle or automatic
result return. Use the thread id to assign optional goal state, schedule
attention, inspect work, or retrieve its response. Configured model and
permission defaults apply unless the supported create overrides are supplied.

Find a thread and inspect its current state:

```sh
codex-threadctl list --limit 10
codex-threadctl list --parent THREAD_ID --sort created --limit 5
codex-threadctl search "decision text" --limit 10
codex-threadctl inspect THREAD_ID
```

List a spawned-agent tree or address a member by its canonical task name:

```sh
codex-threadctl agents
codex-threadctl inspect /root/reviewer
codex-threadctl resolve /root/reviewer
```

`CODEX_THREAD_ID` scopes canonical task names beginning with `/root` to the
current tree. Outside that tree, pass `--tree THREAD_ID`. Task names are reusable
routing aliases; `resolve` prints the stable thread id.

Retrieve retained activity or one exact message:

```sh
codex-threadctl items THREAD_ID --limit 10
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

Start input on an idle thread or steer one exact active turn:

```sh
codex-threadctl start THREAD_ID \
  "From coordinator: Check your goal and continue."
codex-threadctl steer THREAD_ID TURN_ID \
  "From coordinator: Focus on the failing test first."
```

The target sees the message as ordinary input. Name the logical sender when it
could be mistaken for direct human input.

`notify` adds advisory agent context without starting a turn. `wake` starts an
empty turn on a loaded idle target:

```sh
codex-threadctl notify THREAD_ID --from AUTHOR \
  "Stream STREAM_ID has a checkpoint through POSITION."
codex-threadctl wake THREAD_ID
```

When a native subagent tool returns canonical task names, the parent retains
ownership of its v2 children. Threadctl can inspect them by task name, but
current Codex rejects direct `start`, `steer`, `wake`, and `notify`. Create an
independent root instead when external direct control is required.

Other immediate operations include resuming persisted state, interrupting one
turn, and inspecting or terminating a tracked terminal process:

```sh
codex-threadctl resume THREAD_ID --continue-goal
codex-threadctl interrupt THREAD_ID TURN_ID --wait
codex-threadctl terminals THREAD_ID
codex-threadctl terminate-terminal THREAD_ID PROCESS_ID --item ITEM_ID
```

Use `--json` when another program will parse output.

More detail:

- [docs/observation-semantics.md](docs/observation-semantics.md)
- [docs/materialized-history.md](docs/materialized-history.md)
- [docs/lifecycle-control.md](docs/lifecycle-control.md)
- [docs/agent-trees.md](docs/agent-trees.md)

## Codex Skill

Install the optional skill when Codex should know when to use this command:

```sh
codex plugin marketplace add ustas-eth/ferrumctl
codex plugin add codex-threadctl@ferrumctl
```

The skill lives at `plugins/codex-threadctl/skills/codex-threadctl/SKILL.md`.
