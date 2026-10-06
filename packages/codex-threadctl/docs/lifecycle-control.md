# Immediate Thread Control

This reference describes immediate message delivery, execution, loading, and
configuration. `send` carries agent context, `input` carries user input, and
`wake` requests continuation without a message. Loading persisted state is a
separate operation, exposed as `load` or explicitly composed with `--resume`.

The compatibility commands retain their existing behavior and output:
`notify` is agent delivery without wake, `start` is stopped-thread user input,
`steer` is exact-turn user input, and `resume` is an alias of `load`.

## Creating An Independent Root

`create` submits app-server `thread/start` with an explicit working directory,
then appends one short `threadctl` advisory item. That item materializes the
transcript so other app-server clients can address the root before its first
turn. The command prints the returned thread id without starting a turn:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project)
```

The command connects to an existing selected app-server; it does not launch one.
The server supplies its loaded model, provider, reasoning, context, and
permission defaults. Settings on the invoking TUI thread, including its CLI
flags, are not inherited. The new thread is an independent root rather than a
native subagent: no parent receives its result or owns its lifecycle.

Model and effort can be selected at creation:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project \
  --model MODEL_ID --effort high)
```

Add `--model-provider PROVIDER_ID` only when it differs from the server default.
The values are model and provider ids. A native subagent role name is not a
model id, and `create` does not apply that role's configuration. Other native
settings, such as skill selection or context size, can be supplied in a
configuration file.

Approval behavior and execution boundaries are separate choices. The approval
policy determines whether execution can pause for a client decision. A sandbox
or named permission profile defines what local access is available.

Omitting the permission options uses the app-server defaults. When workspace
writes are authorized but no approval-capable client will supervise the worker,
this combination makes disallowed operations fail instead of waiting:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project \
  --approval-policy never --sandbox workspace-write)
```

`--permission-profile NAME` instead selects an existing named Codex policy.
See [Permission Profiles](permission-profiles.md) for configuration selection,
effective-access checks, and observed Codex limitations.

`--approval-policy` can accompany either `--sandbox` or
`--permission-profile`. The sandbox, named-profile, and unrestricted shortcut
forms are mutually exclusive. The shortcut also cannot be combined with a
separate approval policy; it already requests `never` approval and the
`danger-full-access` sandbox together:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project \
  --dangerously-bypass-approvals-and-sandbox)
```

Use that shortcut only when the new worker is authorized for unrestricted host
access. A known named profile can provide a narrower reusable policy for a
recurring worker.

JSON output repeats the submitted values under `permissionRequest`. These are
creation inputs. `settings` contains the server-returned configuration, including
the selected profile when supplied by Codex; neither proves that every intended
access rule works.

The successful response confirms creation, not model execution. A connection or
malformed response after submission leaves the outcome uncertain; list recent
threads before retrying to avoid creating a duplicate. Closing the command's
connection can eventually leave the new root `notLoaded`, while the persisted
thread remains. Later resume requires explicit acknowledgement that an active
goal may continue.

## Endpoint Ownership

Notification, wake, starting, steering, interruption, and terminal-process
control require the target to be loaded on the selected app-server. A thread id
identifies persisted state under a Codex home, but it does not identify which
server currently owns live execution.

## Creation And Resume Configuration

`create --config-file FILE` reads a caller-local TOML file and sends its settings
in the native `thread/start.config` field. This permits worker-specific settings
on a shared server without changing its global configuration:

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project \
  --config-file ./worker.toml --model MODEL_ID --permission-profile worker)
```

For example, `worker.toml` can exclude one skill from the worker's available
catalog while leaving other skills enabled:

```toml
[[skills.config]]
name = "lucid:lucid"
enabled = false
```

The file contains ordinary Codex settings, not `[profiles.NAME]` tables or a
profile selector. It is submitted as request overrides, not loaded as Codex's
CLI `--profile` configuration layer. Supported keys and their behavior are
defined by the selected Codex version.

Explicit flags take precedence over file values. A permission-profile or sandbox
flag also removes the file's competing `sandbox_mode` and `default_permissions`
selectors. The file itself is not modified. TOML dates and non-finite numbers are
rejected locally because they cannot be represented in the JSON request.

The filename is resolved on the caller's host. Paths inside it retain native
Codex semantics on the server; they are not rebased to the file's directory.
Use absolute server-visible paths when location matters. Native skill paths were
observed to resolve against the thread's working directory.

Keep the file available and reapply it on cold resume:

```sh
codex-threadctl load "$WORKER" --continue-goal --config-file ./worker.toml
```

Request overrides are not a durable profile binding. Isolated tests on Codex
source revision `4aa808c` found that skill exclusions did not survive server
restart without being resubmitted; resubmitting them restored the filtered
catalog. A changed catalog does not erase older catalog text or previously read
instructions from the conversation. Skill selection is not a filesystem access
boundary.

`--config-file` is available only for creation and unloaded-thread resume.
`configure` exposes the smaller native live-settings API. Resume refuses file
overrides for an already loaded thread rather than silently treating them as a
live update. Another client can still win the loading race.

JSON `configRequest.keys` lists submitted top-level configuration keys without
echoing their potentially sensitive values. It is a request record, not an
effective-configuration report. The separate `settings` field contains only
settings that the server reports; it cannot confirm arbitrary file settings.
Verify the behavior that matters before relying on it.

## Loading Persisted State

`load` calls native `thread/resume` on the selected server without adding a user
message. Codex emits the thread's goal snapshot after the resume response and
can immediately continue an active goal when the resumed thread is idle.

Resume is a loading operation, not a failed-turn retry. If a thread is already
loaded in `systemError`, load can return that same state. Use `input` when a
new ordinary input is needed or `wake` when its retained context and goal are
enough to continue.

App-server does not provide an atomic "resume only if no goal is active"
operation. Both `load` and its `resume` alias therefore require `--continue-goal`. The
flag acknowledges possible continuation; it does not activate or change the
goal. Resume also does not detect or coordinate another app-server that may
have loaded the same thread.

For an unloaded thread, settings overrides travel in the loading request so an
active goal need not resume under old settings first:

```sh
codex-threadctl load THREAD_ID --continue-goal --model MODEL_ID --effort high
```

Omitted settings use Codex's resume behavior: persisted turn settings where
supported, and applicable configuration for the rest. This is the shared
app-server resume path, not a standalone `codex exec resume` invocation with its
own CLI configuration. JSON `settings` reports the server's response.

Threadctl refuses resume overrides when the target is already loaded; use
`configure` for supported live settings. Another client can still load it between
that check and the request. If returned settings do not match explicit settings
flags, the command reports a partial outcome: the thread was resumed and its
goal may already be continuing, but the overrides were not confirmed.

Current Codex rejects direct app-server input and raw-item injection to
parent-owned v2 subagents. Control them through their native parent handle;
threadctl wake, input, and send apply to threads that accept direct input.

## Updating A Loaded Thread

```sh
codex-threadctl configure THREAD_ID --model MODEL_ID --effort high
codex-threadctl configure THREAD_ID --permission-profile worker --approval-policy never
```

`configure` sends only the supplied fields to `thread/settings/update`, leaving
the rest unchanged. Codex applies these settings to subsequent turns; the
command neither interrupts current work nor starts a turn. The response confirms
acceptance, not execution under the new settings. It requires a loaded thread
and a Codex version supporting that method; an unsupported request fails without
falling back to a new session or another launch path. Provider and context-window
overrides are outside this command's scope.

## Machine-Readable Failures

With `--json`, runtime failures emit an `error` object with `code`, `outcome`,
and `message`, plus known reconciliation identifiers. Exit status remains
nonzero, and a human-readable error is also written to stderr. Parser errors
retain argparse's usage output. Wake outcomes and a `send --wake` partial result
retain their operation records described below, rather than an `error` wrapper.

`partial` means an earlier step succeeded, such as root creation before its
initialization item failed. `uncertain` means a submitted operation may have
taken effect. A generic `failed` outcome makes no claim about side effects;
inspect before repeating a mutation. A known created thread id is included
even when initialization fails, so recovery need not create another root.

## Agent Messages

`send` submits one raw `agent_message` to a loaded target through
`thread/inject_items`. Its author defaults to `CODEX_THREAD_ID` and its
recipient is the target thread id. The text is advisory agent context rather
than a user message.

Threadctl assigns the raw item an `amsg_` id and returns it as `itemId` in JSON
output. An uncertain notification reports the same id for reconciliation. The
materialized conversation view may assign its own item locator, so use the
notice text or raw rollout when that original id must be found later.

The text can be a complete report, question, request, or correction. Hierarchy
does not change its role: a coordinator's message and a worker's report are both
agent communication. When a stream is the chosen durable exchange, a message
can instead announce its latest position. Neither a stream nor a separate file
is required for direct communication.

`send --stdin` reads the exact text from redirected standard input instead of
a positional message; `input --stdin` provides the same interface for deliberate
user input. Empty text and simultaneous sources are rejected before connecting:

```sh
codex-threadctl send THREAD_ID --from WORKER_ID --stdin --json < report.txt
```

Plain `send` does not start a turn. A message can become available at a later
model step, including during active reasoning, but app-server returns no native
delivery disposition. Success means only that the injection request was
accepted. It does not prove timing, retained materialization, model receipt, or
action. Notice arrival also does not establish the order of the durable events
it announces.

A connection failure after submission has an uncertain outcome. Do not retry
automatically. Agent messages can be absorbed or retained by compaction, so
`send` is neither an ephemeral event channel nor a durable mailbox. For stream
announcements, nearby appends can be batched into one notice of the latest
position; the stream's durable acknowledgement needs no separate notice.

A later response or state change does not reveal which channel prompted it.
When transport choice matters, verify the operation that was actually submitted
rather than inferring it from the recipient's behavior.

`send --wake` follows accepted injection with an empty wake. JSON separates
`messageOutcome: accepted`, its `itemId`, and the nested `wake` result. A failed
or unconfirmed wake produces `outcome: partial` and nonzero exit status without
undoing or resending the message. If injection itself is uncertain, no wake is
attempted. Reconcile the agent-message id before repeating the send.

## Empty Wake

`wake` first observes the target on the selected app-server. If it is active,
the command submits nothing and reports `notSubmittedActive`. If it is `idle`
or `systemError`, the command calls `turn/start` with an empty input list. The
model receives its existing context without a new user message. Codex clears
the error state when the new turn starts; threadctl does not assume that the
underlying service problem has cleared.

The stopped-state check and turn start are not atomic. Threadctl confirms the
exact turn returned by app-server through a start notification or materialized
turn history. The machine outcomes are:

- `confirmedStarted`: the returned turn was observed
- `notSubmittedActive`: the target was already active
- `notLoaded`: the selected app-server does not own the target
- `rejected`: the observed state or app-server rejected the operation
- `uncertain`: submission may have happened but the exact turn was not confirmed

Only the first two outcomes exit successfully. Plain `wake` does not load an
unloaded thread, intentionally steer active work, add instructions, or change
goal state.
`confirmedStarted` confirms the returned turn's identity, not successful model
work or turn completion; observe the turn or goal separately when that matters.
`notSubmittedActive` is a point-in-time result; it does not arrange another
turn after the observed active turn ends.

### Explicit Cold Recovery

```sh
codex-threadctl wake THREAD_ID --resume --config-file ./worker.toml
codex-threadctl send THREAD_ID "The test results are ready." --wake --resume
```

`--resume` permits loading on the selected server, including possible goal
continuation. For `send` it requires `--wake`, since loading can itself start
work. A configuration file requires `--resume` and is submitted only if the
thread was observed unloaded. Already-loaded targets keep their settings;
`loading.configSubmitted` is false in that case. A true value records submission,
not verification of every native setting. `loading.settings` contains the
server-reported subset. Another client can still win the loading race.

Cold recovery checks goal state around loading. With an active goal, it observes
whether a new turn appears instead of immediately adding another turn. The
additional successful outcome `confirmedResumed` means a new turn was observed
after loading, not that its work succeeded or that this caller uniquely caused
it. `continuationUnconfirmed` exits nonzero: loading succeeded but no new turn
was observed within the confirmation timeout. Inspect before intervening again.
When no active goal was observed, the normal empty-wake operation follows.
For `send --wake`, a continuation observed before message submission does not
substitute for attention to the new message: the normal post-send wake check
applies, so a continuation that already finished cannot swallow the request.

This is a sequence of native operations, not an atomic recovery transaction.
Concurrent goal or turn changes can still race with it. Loading can begin goal
work before `send` injects its text. If message submission fails after loading,
the error preserves the loading result and message outcome. No step reactivates
a stopped goal, changes models automatically, or retries a failed service.

## Starting Input

`input` without `--turn` observes a loaded thread as `idle` or `systemError`,
submits `turn/start` with a unique client message id, and waits until it appears in
materialized turn history. The result reports the actual turn id and whether
Codex started a new turn or steered the message into a turn that won the race.

JSON output includes the client message id used for confirmation. Materialized
item ids can change while an app-server catches up with earlier history, so
`input` does not present the initially observed item id as a durable boundary.
After the turn stops, use its exact turn id to retrieve the response. The
client message id confirms delivery; it does not identify the logical sender.
An origin label in the text does not change its user role.

The canonical `input` result includes `messageRole: user`. The stopped-state
observation and `turn/start` request are not atomic.
Confirmation makes the outcome visible but cannot undo input that raced into
active work. If confirmation fails, the operation is uncertain: retrying can
duplicate the message.

Starting from `systemError` confirms only the new turn and delivery mode. It
does not prove the previous turn made no progress or that the model is now
available. Inspect the failed turn before repeating non-idempotent work, then
observe the returned turn and stop or choose another policy if it fails again.

Early Codex 0.144 item pagination omits turn attribution. A matching bare item
proves persistence but not which turn accepted the message, so threadctl waits
for an attributed item notification or turn view. If neither becomes
available, `input` reports an uncertain outcome instead of substituting the
submitted turn id.

## Steering

`input --turn TURN_ID` uses native `turn/steer` with an expected turn id. Codex
rejects the request if it is no longer the active regular turn. Review and manual
compaction turns do not accept steering.

A rejected JSON-RPC request is a definite failure. A connection or protocol
failure after start or steer was submitted has an uncertain outcome and should
be reconciled by client message id before retrying. Structured `inspect` and
`messages` output preserves that id when Codex materializes the message.

Threadctl does not answer approval or user-input requests raised later by the
turn. A capable app-server client must remain available to resolve them.

## Interruption

`interrupt` sends `turn/interrupt` for an explicit thread and turn id. Native
turn-id validation prevents a stale request from interrupting a replacement
turn.

The immediate result is an interruption request, not terminal completion. With
`--wait`, threadctl follows that exact turn until materialized history reports a
terminal status. Interruption does not pause a goal or terminate background
terminals.

## Terminal Processes

`terminals` lists processes that Codex still tracks for one loaded thread. Each
record includes the native process id used by app-server, its originating item,
command, and working directory, with OS resource fields when available.

Codex can reuse process ids after a terminal exits. `terminate-terminal`
therefore requires both the process id and originating item id from a current
`terminals` listing. Threadctl re-lists the thread and rejects a missing process
or changed item before sending the native termination request.

The identity check and native request are not atomic because app-server accepts
only the process id. Use a fresh listing and act promptly. Success means
app-server confirmed termination; failure does not by itself prove the process
was absent. Termination does not interrupt the model turn or change goal state.
When a thread inspects itself, the inspection command can appear in the result
while it is still running.
