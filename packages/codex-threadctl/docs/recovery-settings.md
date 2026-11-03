# Remembered Recovery Settings

Codex persists a thread's model, provider, reasoning effort, approval policy,
working directory, and selected permission profile. Other request overrides,
such as skill selection, context size, or request-only permission definitions,
can be lost on cold loading. Threadctl retains those supplementary values so
continuing a worker does not require rebuilding its launch file.

## Creation And Cold Loading

```sh
WORKER=$(codex-threadctl create --cwd /path/to/project --config-file ./worker.toml)
codex-threadctl wake "$WORKER" --resume
```

Creation saves the explicit supplementary settings, not resolved server defaults
or the filename. The source file can be moved or deleted. Paths inside the saved
settings still resolve on the server according to native Codex rules; referenced
files, skills, and executables are not copied.

`load`, `wake --resume`, and `send --wake --resume` read the record only when
loading an unloaded thread. The values enter the same `thread/resume` request
that may continue an active goal. An already loaded thread keeps its settings.
Native TUI resumes and other clients do not consult this local record.

Codex remains responsible for its persisted selections. Threadctl does not save
old model, provider, effort, approval, sandbox, permission-profile selector, or
cwd values for later replay. A model or permission selection changed through
another client therefore is not replaced by the worker's original launch value.
Saved request-only profile definitions are snapshots; replacing their source
TOML does not update them.

## Override Or Replace

A configuration file supplied during cold loading overrides the remembered
values by top-level key. Nested tables and arrays are replaced as whole values,
not recursively merged. Explicit command flags still take precedence:

```sh
codex-threadctl load "$WORKER" --continue-goal --config-file ./changes.toml
```

After successful loading, supplementary overrides from the file are saved with
the retained values. Rejected or uncertain loading does not update the record.
An empty file adds no overrides; use `recovery` to replace the complete record
or remove it.

Inspect, replace, or forget a record without loading the thread or changing live
settings:

```sh
codex-threadctl recovery "$WORKER" --json
codex-threadctl recovery "$WORKER" --values --json
codex-threadctl recovery "$WORKER" --config-file ./worker.toml
codex-threadctl recovery "$WORKER" --forget
```

An existing thread can be registered through the same replacement command.
Threadctl does not infer its original overrides from conversation text. Raw
thread ids permit these local operations while the server is down; a canonical
task name requires the server to resolve it.

`--no-recovery` on creation or cold loading bypasses both record reads and writes.
Explicit file settings can still be submitted through the native operation.
For loaded settings, use `configure`; it neither applies nor changes recovery
overrides.

## State And Identity

The default SQLite store is:

```text
$XDG_STATE_HOME/codex-threadctl/threads.sqlite3
```

It falls back to `~/.local/state/codex-threadctl/threads.sqlite3`. Override it
with `--state PATH`. The default directory is mode `0700` and the database is
mode `0600`. Existing custom paths retain their permissions.

A record is keyed by normalized app-server endpoint and thread id. Bare
`unix://` is resolved before lookup. The caller's Codex home is not assumed to
identify a remote server's store. Changing the endpoint requires registering
the record under the new endpoint. The endpoint is a routing scope, not an
authenticated store identity; use separate state files if the same address
and thread ids are reused for different stores.

Known inline credential fields are rejected before saving; environment-based
credential references remain usable. Keep secrets out of saved configuration:
this check cannot identify every possible sensitive value. Normal output lists
keys, not values; `--values` deliberately exposes the saved configuration.

Record writes are transactional. If another caller replaces or forgets a record
during loading, the later save fails without overwriting that edit. A native
operation can succeed before a local save fails: the command reports a partial
outcome with the thread id. Repair the record instead of creating or loading
another thread blindly.

## Scheduled Recovery

Wakectl event jobs with `--resume` use the same loading implementation and
recovery store. New jobs retain the caller's resolved recovery-state path; use
wakectl's `--recovery-state PATH` for a custom store, or `--no-recovery` to bypass
it. Wakectl's `--state` continues to select the wake queue, not thread settings.

Without an explicit job configuration, the runner reads the current record at
delivery time. `--config-file FILE` on a job saves a separate snapshot that
overrides remembered values for that delivery; it does not update the thread's
record. Editing or forgetting the record does not remove an explicit job
snapshot.

## Confirmation Boundary

Isolated tests on Codex 0.161.0 verified native selections before the first
model turn and after later settings changes. Recovery relies on the selected
server's native persistence behavior.

JSON `recovery` identifies the local record and submitted keys; `settings`
contains the server-reported subset. Neither verifies every configuration key
or proves that an access rule works. Another client can win the loading race,
and goal continuation may start before a mismatch is observed. Recovery is not
an atomic configuration-and-execution transaction.
