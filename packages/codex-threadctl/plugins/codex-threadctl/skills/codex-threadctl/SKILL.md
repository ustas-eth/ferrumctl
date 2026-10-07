---
name: codex-threadctl
description: "Use to discover or inspect Codex threads beyond native results, create independent workers, exchange agent messages, or control threads through a thread id or canonical task name. Prefer native tools when this session owns the live child. Do not use for future conditions, goal editing, terminal keystrokes, or native subagent spawning."
---

# Codex Threadctl

Use `codex-threadctl` for retained history and immediate control on a shared
app-server (`unix://` by default). Prefer native subagent tools for ordinary
messages, waiting, and control when you own the live child handle.

## Choose The Operation

| Need | Command |
| --- | --- |
| Understand current state and recent work | `inspect THREAD_ID` |
| Send a report, question, request, or correction as an agent | `send THREAD_ID "TEXT"` |
| Also request attention if the recipient is stopped | `send THREAD_ID "TEXT" --wake` |
| Continue from existing context without a message | `wake THREAD_ID` |
| Deliberately provide user input to a stopped thread | `input THREAD_ID "TEXT"` |
| Steer user input into an exact active turn | `input THREAD_ID "TEXT" --turn TURN_ID` |
| Load persisted state, allowing a goal to continue | `load THREAD_ID --continue-goal` |
| Stop an exact turn | `interrupt THREAD_ID TURN_ID --wait` |

Routine coordinator requests and worker reports are agent communication.
`send` carries the text itself; it is not limited to notices or file pointers.
Its author defaults to `CODEX_THREAD_ID`; use `--from` when a host process needs
an explicit identity. Author labels are provenance, not
authentication or added authority.

`send` alone does not start work. `--wake` adds a separate empty-turn request if
the recipient is stopped. Acceptance does not prove that the model read or acted
on the message. Agent context may survive compaction, but is not a durable
mailbox. Use a stream, when available, if shared ordering and processed-through
acknowledgements matter; an ordinary direct exchange does not require one.

Use `input` deliberately when user-role instructions are needed, including a
brief anchor for ongoing goal-driven work after a focused exchange. Identify
the sender in the text; read `references/coordination-principles.md` for when
renewing that frame is useful.

The older `notify`, `start`, `steer`, and `resume` commands remain compatible:
they correspond to `send`, `input`, `input --turn`, and `load` respectively.

## Create And Continue A Worker

Use an independent root when other threads or host processes must control it
directly. Native v2 children remain parent-owned and reject direct external
input and injection; resolving their task names or loading them does not change
that ownership.

```sh
WORKER=$(codex-threadctl create --cwd "$PWD")
codex-threadctl send "$WORKER" "Review this package and report your findings." --wake
```

`create` persists a root without starting a turn. It has no native parent handle
or automatic result return. Retain its thread id. The server's defaults apply,
not this session's settings:

- Select `--model MODEL_ID` and `--effort` when needed. Add `--model-provider`
  only for a non-default provider. A native agent role is not a model id.
- Use `--config-file FILE` for other native Codex settings, including skills and
  context size. Explicit flags win. Keep the TOML file for cold loading; the
  overrides are not a saved profile binding.
- Choose permissions for the assignment. An existing `--permission-profile`
  names a filesystem/network policy, not a general configuration profile. With
  no approval-capable client, `--approval-policy never` prevents approval waits
  but grants no access. Unrestricted access requires deliberate authorization
  for the new worker, regardless of your own access.

If work is already assigned in a goal or retained context, use `wake`. Add
`--resume` when loading the persisted thread on this server is intended:

```sh
codex-threadctl wake "$WORKER" --resume --config-file ./worker.toml
```

The file is submitted only during cold loading; output reports when it was not
applied because the thread was already loaded. Use `configure` for supported
live changes. `send --wake` also accepts `--resume` and `--config-file`.
Loading may continue an active goal before a new message arrives.

An active target keeps running; a loaded `idle` or `systemError` target can
receive an empty turn. After cold loading with an active goal, threadctl checks
for continuation instead of blindly starting twice. An unconfirmed continuation
is not success. Inspect the returned turn before deciding whether recovery
worked; a new turn can fail on the same underlying problem.

## Read History

```sh
codex-threadctl list --sort recency --limit 10
codex-threadctl search "decision text" --limit 10
codex-threadctl inspect THREAD_ID --brief
codex-threadctl items THREAD_ID --limit 10
codex-threadctl messages THREAD_ID --limit 10
codex-threadctl message THREAD_ID TURN_ID ITEM_ID
```

Use `message` or JSON for complete retained text. Use `items --after TURN_ID
ITEM_ID` or `messages --after TURN_ID ITEM_ID` for an exclusive range; `--limit 0`
reads the whole selected interval. Materialized history is a conversation view,
not an immutable log: an active turn's item ids can change.

`agents` lists a native tree; `resolve /root/reviewer` returns a thread id.
Canonical task names work directly in threadctl commands. `CODEX_THREAD_ID`
scopes them to your tree; pass `--tree THREAD_ID` for another. Resolve and retain
the id when another package needs it or a reused task name would be ambiguous.

## Interpret Results

Live state belongs to the selected server. `notLoaded` does not mean finished;
`idle` does not mean the goal is complete. `inspect` separates live state,
recorded settings, history, and goal budget; check observation times.

Use `--json` for exact outcomes and reconciliation ids. In `send --wake`, message
acceptance and wake confirmation are separate: a failed wake does not mean the
message should be resent. An uncertain submission may already have taken effect.
Inspect before retrying. User `input` can race into a newly active turn; read its
actual delivery result rather than assuming a new turn started.

For later attention, use scheduling when its skill is available. For a current
terminal process, use `terminals` and `terminate-terminal` with both process and
item ids from a fresh listing. Neither interruption nor process termination
pauses a persisted goal.

## References

- Read `references/lifecycle-control.md` for configuration, cold loading,
  exact delivery outcomes, compatibility commands, or ambiguous recovery.
- Read `references/permission-profiles.md` for named policies, precedence, or
  unexpected access and missing worker instructions.
- Read `references/restricted-operations.md` when a worker needs one-way
  reporting or selected operations without general thread or store access.
- Read `references/observation-semantics.md` for freshness, timestamps, context
  usage, and mixed-source inspection.
- Read `references/materialized-history.md` for exact ranges, pagination, and
  mutable message locators; `references/agent-trees.md` for native ownership or
  task-name reuse.
- Read `references/worker-workflows.md` for sustained supervision;
  `references/peer-workflows.md` for durable discussion;
  `references/host-automation.md` for external managers;
  `references/coordination-principles.md` for cross-tool boundaries.
