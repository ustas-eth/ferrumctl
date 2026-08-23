# ferrumctl

Lightweight control tools for long-running Codex workflows.

Codex can start and message subagents. Once work spans many turns, a coordinator
has limited ways to update another thread's goal, wake it after a future
condition, or see enough of its state to decide what happens next.

Ferrumctl fills those gaps with seven independent commands. They run locally on
Codex state available to the same computer and user account, and your coding
agent composes them into its own workflow. The commands stand alone; optional
Codex skills help agents choose and use them correctly.

## What It Adds

| Tool | What it lets your agents do |
| --- | --- |
| [`codex-goalctl`](packages/codex-goalctl) | Set, inspect, or update another Codex thread's durable goal and token budget. |
| [`codex-wakectl`](packages/codex-wakectl) | Return attention after a time, goal, turn, or host condition. |
| [`codex-threadctl`](packages/codex-threadctl) | Find a thread, see its recent work and retained messages, or control its current turn. |
| [`codex-readcov`](packages/codex-readcov) | Check which file reads were recorded in a thread transcript and compare work intervals. |
| [`codex-limitctl`](packages/codex-limitctl) | Check subscription capacity and recent usage before planning more work. |
| [`codex-memoryctl`](packages/codex-memoryctl) | Inspect, export, or deliberately transfer opaque Codex compaction memory. |
| [`streamctl`](packages/streamctl) | Keep a durable, ordered exchange between agents or host scripts. |

## A Typical Use

You ask a main Codex thread to review a project with two workers. With the
matching ferrumctl skills available, the coordinator can:

1. Give each worker a durable goal and budget.
2. Start their work and arrange to wake when either worker stops.
3. Inspect current activity or retained answers while their work continues.
4. Check goal status and recorded file reads before choosing the next step.

The coordinator performs these operations itself, removing manual goal copying,
repeated worker polling, and raw transcript searches. Native controls remain
simpler for quick exchanges with a live subagent.

The same tools also support self-scheduling agents, paired reviews, and host
automation.

## Install

Give this repository to your coding agent with a request such as:

> Install ferrumctl from https://github.com/ustas-eth/ferrumctl. Enable the
> commands and Codex skills that fit my workflow. Before changing how I start
> Codex, explain the shared app-server setup to me.

[Install and upgrade](docs/install-and-upgrade.md) contains the full procedure.
The commands remain ordinary Unix tools, so humans and scripts can also call
them directly.

## One Setup Requirement

Live thread control and scheduled wakes require the relevant Codex sessions to
share one app-server. Keep the server running in one terminal:

```sh
codex app-server --listen unix://
```

Start or resume controlled sessions through it:

```sh
codex --remote unix://
```

On a Linux host with user systemd, install the `codex-wakectl` timer once for
automatic wake delivery:

```sh
codex-wakectl systemd install --interval 30s
```

Your agent can install the timer. You must keep the app-server running and
restart it when updating Codex.

Some commands depend on Codex app-server methods and local transcript formats.
These can change between Codex releases, so check for ferrumctl updates after
upgrading Codex.

## Learn More

- [Install and upgrade](docs/install-and-upgrade.md)
- [Worker workflows](docs/worker-workflows.md)
- [Peer workflows](docs/peer-workflows.md)
- [Host automation](docs/host-automation.md)
- [Coordination principles](docs/coordination-principles.md)

Each package keeps its own examples and detailed mechanics beside the code.
See [CONTRIBUTING.md](CONTRIBUTING.md) for development and publishing rules.

## License

[MIT](LICENSE)
