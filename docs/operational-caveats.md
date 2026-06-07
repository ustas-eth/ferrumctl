# Operational Caveats

This reference collects reliability limits that matter when ferrumctl commands
are composed.

Some workflows use only one skill. Apply only the caveats for the skills and
surfaces actually involved.

For humans and scripts, an installed command is enough. For Codex agents, a
missing skill means the agent lacks the intended guidance for that command; use
native controls or ask for the skill/tooling unless the user explicitly asks for
the command.

## Goal State

Goal writes are persisted state changes, not input turns. Do not assume that
changing a goal wakes a CLI-owned thread.

Goal status is durable assignment state, not app-server activity. A thread can
have an `active` goal while app-server status is `idle`, especially after an
external goal write that the thread has not yet observed. Do not treat
app-server `idle` as availability for unrelated work.

`codex-goalctl replace` is clear-then-set, not an atomic app-server primitive.
If another process reads or writes the same goal during that window, it may
observe the cleared state or overwrite the new state.

Concurrent writes to the same goal are last-writer-wins. Use one owner for a
thread goal when possible.

## Live Wakes

`codex-wakectl` can wake only threads loaded on the selected app-server. A valid
thread id is not enough.

Queued wakes require a runner. A queued job will not fire unless
`codex-wakectl run`, systemd, or another scheduler checks the queue.

Delivery is best treated as at-least-once. A wake may arrive late, duplicate
after a runner crash, or become redundant after manual handling. Wake messages
should be idempotent.

By default, wakes send only to idle target threads. Use `--allow-active` only
for messages that are safe while the target keeps running. For checkpoints,
wait until the target stops so the answer can be inspected before continuation.

Sending to an idle goal-backed worker is appropriate when the message is meant
to make it observe or continue the current goal, such as asking it to call
`get_goal`. For new assignments, checkpoints, or changed ownership, update the
goal state deliberately instead of relying on turn idleness.

Create `stop` watches before the turn they should observe can stop. A stop that
already happened is not a durable event to replay later.

Repeating conditions should have an owner and, when appropriate, a cap. Cancel
stale jobs when the coordination loop is over.

## Read Coverage

`codex-readcov` is transcript-derived evidence, not OS-level audit data. It
does not prove every file descriptor opened by a process.

Path operands filter reported reads; they do not define the universe of files
that should have been read. Negative coverage is a separate set operation over
an expected file list.

For live rollouts, repeated reads of the same open-ended window may include
more events later. Use explicit start and end snapshots when a fixed interval is
needed.

The result depends on Codex rollout schema and the command parser used by
`codex-readcov`.

## Cross-Surface Workflows

Persisted goal state, live app-server state, and rollout transcripts are
different surfaces. They can be temporarily inconsistent.

Prefer workflows that tolerate retries:

- write durable intent to the goal
- send small wake messages that tell the target what to inspect
- snapshot before the interval being measured
- cancel queued wakes once their purpose is complete
- use `--json` for machine parsing

When a native subagent handle is available, native input is usually the cleanest
immediate message channel. Native wait or poll is useful only when blocking the
coordinator is acceptable; queued wakes are better for durable later attention.
