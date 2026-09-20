# ferrumctl

Let your coding agent coordinate long-running work.

Ferrumctl lets a Codex coordinator create worker threads, assign goals and
budgets, check progress, and arrange follow-ups. You guide the work and review
the results; your agents handle the routine coordination.

Workers can pursue their goals independently while the coordinator observes
their progress and adjusts assignments. They can also schedule their own
follow-ups and exchange findings directly with peers.

Six small, independent tools make this possible. Use them separately or let
your agent combine them into a workflow. Optional Codex skills help agents
choose and use the right commands.

## What It Adds

| Tool | What it lets your agents do |
| --- | --- |
| [`codex-goalctl`](packages/codex-goalctl) | Set, inspect, or update another Codex thread's durable goal and token budget. |
| [`codex-wakectl`](packages/codex-wakectl) | Wake an agent later or when a condition is met. |
| [`codex-threadctl`](packages/codex-threadctl) | Create worker threads, inspect their progress and conversation history, or send input and interrupt work. |
| [`codex-limitctl`](packages/codex-limitctl) | Check subscription capacity and recent usage before planning more work. |
| [`codex-memoryctl`](packages/codex-memoryctl) | Help agents recall older work or consult another thread's compaction memory. |
| [`streamctl`](packages/streamctl) | Give agents a shared conversation with saved messages and read acknowledgements. |

## A Typical Use

You ask your main Codex thread to review a project using two separate worker
threads. With the matching ferrumctl skills available, it can:

1. Create each worker in the right project and give it a durable goal and budget.
2. Start their work and arrange to wake when either worker stops.
3. Inspect current activity or retained answers while their work continues.
4. Review the results and goal status before choosing the next step.

Native subagents are still useful for delegated tasks that return an answer to
their parent. Separate worker threads allow the direct control shown here;
see [worker workflows](docs/worker-workflows.md) for the distinction and current
Codex limitations.

## Install

Give this repository to your coding agent with a request such as:

> Install ferrumctl from https://github.com/ustas-eth/ferrumctl. Enable the
> commands and Codex skills that fit my workflow. Before changing how I start
> Codex, explain the shared app-server setup to me.

[Install and upgrade](docs/install-and-upgrade.md) contains the full procedure.
The commands remain ordinary Unix tools, so humans and scripts can also call
them directly.

## Shared App-Server Setup

The tools run locally, using Codex state on the same computer and user account.
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
