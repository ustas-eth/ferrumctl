<!-- Generated from docs/coordination-principles.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Coordination Principles

This reference explains how ferrumctl commands compose, and how Codex skills
expose those commands to agents.

The commands do not form one scheduler or one state machine. Each command
exposes a small surface that can be combined with native Codex controls, shell
scripts, or another agent's workflow.

## Surfaces

`codex-goalctl` edits persisted goal state for a thread. It is most useful when
one session manages another session's durable intent. For the current thread,
native goal tools are usually better when available.

`codex-wakectl` sends input turns and schedules wake conditions for threads
loaded on a selected Codex app-server. It is the tool for self-wakes,
supervisor wakes, peer handoffs, and long waits that should resume later.

`codex-readcov` reads rollout transcripts and reports file-read evidence. It is
useful for worker audits, self-audits, negative coverage, and comparing what
several workers actually inspected.

## Thread Identity

The common handle is a Codex thread id. For v1 Codex subagents, the spawn
result's `agent_id` is the thread id.

`CODEX_THREAD_ID` identifies the current Codex thread when Codex provides it.
It does not prove that the thread is loaded on a shared app-server.

## Native And Host Control

Native subagent input is the best immediate channel when the current session has
the live subagent handle and needs to send a message now.

Native wait or poll is useful when the current turn should stay active and
blocking for the worker is acceptable. For long-running goal work, it is often
better to let the coordinator stop and use a later wake.

Use ferrumctl when the useful handle is a thread id, when the current turn
should stop and be resumed later, when another host process is coordinating, or
when durable goal/read state must be inspected outside the target thread.

## Goal And Turn State

App-server status and goal status answer different questions. App-server
`idle` means no turn is running right now. It does not mean the thread is free
for unrelated work, and it does not prove the thread has observed a recently
written goal.

A thread with an `active` goal and app-server `idle` status has durable work
assigned, but no turn is currently acting on it. A short input message that
tells the worker to call `get_goal` is often what starts or resumes that work.

## Commands And Skills

The command is the host executable. The skill is the agent-facing guidance for
when and how to use that executable.

Humans and scripts can use installed commands directly. Codex agents should
normally use only the command surfaces whose skills are available in the current
context, unless the user explicitly asks for a command or installs the missing
skill.

Useful command/skill subsets:

- `wakectl`: self-reminders, peer handoffs, stop watches, command predicates.
- `goalctl`: external goal assignment and status checks, but no wake.
- `readcov`: transcript read audit, gaps, overlap, and self-meta inspection.
- `goalctl + wakectl`: durable assignment plus live delivery.
- `wakectl + readcov`: wake/resume sessions and inspect what they read.
- `goalctl + readcov`: durable assignment and later audit, with wake supplied
  by native or manual input.

Missing skills remove the agent-facing guidance for that surface; they do not
change the semantics of the other commands.

## Divergence

The surfaces can diverge temporarily:

- a goal can be updated while a CLI-owned thread remains asleep
- `goalctl` can edit persisted state through its own short-lived app-server
  while `wakectl` talks to a shared live app-server
- a wake can arrive after the condition was handled manually
- a live rollout can grow while `readcov` scans it

Treat cross-surface workflows as retryable. Put durable intent in goals, make
wake messages small and idempotent, snapshot before the interval being measured,
and cancel stale queued wakes.
