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

## Scheduled Wakes

`codex-wakectl` can wake only threads loaded on the selected app-server. A valid
thread id is not enough.

Queued wakes require a runner. A queued job will not fire unless
`codex-wakectl run`, systemd, or another scheduler checks the queue.

Command predicates run with the runner's environment and must remain true until
a runner observes them. The built-in systemd units process one selected state
database; installing them again for another `--state` replaces that selection.

Delivery is best treated as at-least-once. A queued wake may arrive late,
duplicate after a runner crash, or become redundant after manual handling.
Queued wake messages should be short and idempotent unless the delayed input is
deliberately meant to be the instruction.

By default, wakes send only to idle target threads. Use `--allow-active` only
for messages that are safe while the target keeps running; active delivery uses
native expected-turn steering. The idle check and native start request are not
atomic, so the recorded delivery mode can still be `steered` if another turn
wins that race.

An input submission whose outcome cannot be confirmed becomes `uncertain` and
is not retried automatically. Inspect the target and use its client message id
before deciding whether another message is safe.

Codex rejects direct app-server input to v2 subagents; use their native parent
handle. Turns started through ferrumctl can still request approval or user
input, which a capable app-server client must resolve.

Sending to an idle goal-backed worker is appropriate when the message is meant
to make it observe or continue the current goal, such as asking it to call
`get_goal`. For new assignments, checkpoints, or changed ownership, update the
goal state deliberately instead of relying on turn idleness.

Create `stop` watches before the turn they should observe. The job records the
newest turn as its cursor, then detects later terminal turns from persisted turn
history. Several completions between runner passes are coalesced into one wake.
If that cursor disappears, the job fails rather than treating older history as
a new completion.

A wake sent by a running thread can arrive before that thread's final response
is committed. A terminal goal status can also be observed before the current
turn ends. Use a stop watch or deliberate thread inspection when the receiver
depends on a confirmed turn boundary rather than a readiness signal.

A wake carries input to its target; it does not carry another thread's response
back. Retrieve a native subagent result through the native handle. For standalone
threads, put results in a shared artifact or inspect the thread deliberately.

Repeating conditions should have an owner and, when appropriate, a cap. Cancel
stale jobs owned by that coordination loop when it is over. The default
wakectl queue is shared; unrelated jobs may be pending in the same database.
Every goal watch belongs to one goal assignment. A replacement assignment marks
the old watch `superseded`.

## Thread Observation And Control

`codex-threadctl inspect` combines several app-server requests with selected
rollout records. A running thread can advance while the report is assembled;
the result is orientation, not an atomic snapshot.

Materialized turn history can change after rollback or compaction. Persisted
items are lossy and do not include every transient interaction or item
timestamp. A message locator therefore uses both its turn id and item id.

Context usage is the latest recorded model exchange. It may remain unchanged
during a long command and should be interpreted with its observation age. Goal
token counters are cumulative and are not context-window usage.

Immediate input and interruption require a loaded target. `start` confirms the
actual delivery mode, while `steer` and `interrupt` require an expected turn id.
Interruption reports `requested` unless the caller waits for terminal status;
it does not pause a goal or terminate background terminals. `resume` loads
persisted state but does not coordinate another server that may own the same
thread.

## Read Coverage

`codex-readcov` reports transcript-recorded read actions, not OS-level audit
data. It does not verify command success or prove every file descriptor opened
by a process.

Path operands filter reported reads; they do not define the universe of files
that should have been read. Negative coverage is a separate set operation over
an expected file list.

For live rollouts, repeated reads of the same open-ended window may include
more events later. Use explicit start and end snapshots when a fixed interval is
needed.

The result depends on Codex rollout schema and the command parser used by
`codex-readcov`. Current JavaScript tool envelopes are accepted only when nested
command arguments are statically recoverable; unresolved calls fail the scan
instead of being counted as zero.

## Cross-Surface Workflows

Persisted goal state, live app-server state, materialized turn history, rollout
transcripts, and the wake queue are different surfaces. They can be temporarily
inconsistent.

Prefer workflows that tolerate retries:

- write durable intent to the goal
- prefer small queued wake messages that mark the event
- inspect before steering or interruption
- snapshot before the interval being measured
- cancel queued wakes owned by the workflow once their purpose is complete
- use `--json` for machine parsing

When a native subagent handle is available, native input is usually the cleanest
immediate message channel. Native wait or poll is useful only when blocking the
coordinator is acceptable; queued wakes are better for durable later attention.
