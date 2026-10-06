# Restricted Worker Operations

A worker can publish a report or request a self-wake without receiving general
access to thread control. An operator-owned adapter exposes one operation;
the worker's execution permissions keep the underlying sockets and stores out
of reach. The policy belongs to that deployment, not to a ferrumctl role system.

## Bind One Operation

The adapter's launch arguments fix the operation, target, author, upstream
endpoint, and state path. Requests carry only the permitted payload. A separate
socket can expose a different operation or serve a different worker.

| Operation | Worker supplies | Operator fixes | Receipt |
| --- | --- | --- | --- |
| Report | Message text | Coordinator and author; whether to wake | Message item id and optional wake outcome |
| Signal | Empty object | Notification text, recipient, and author | Message item id and optional wake outcome |
| Append | Entry text | Stream, author, and database | Committed position |
| Self-wake | Delay in seconds | Worker, queue, endpoint, and maximum delay | Scheduled job id |

Reporting uses agent context, not user input. A signal limits the supplied
content to an operator-written notice; a report allows the recipient to reason
about worker-supplied text. Both can influence attention. Waking is a separate
execution permission, enabled explicitly by the operator.

The [example adapter](https://github.com/ustas-eth/ferrumctl/blob/main/examples/restricted-operations/adapter.py)
is a one-shot program, not a server. It reads one UTF-8 JSON line of at most
64 KiB, rejects extra or duplicate fields, calls a fixed executable without a
shell, and returns only the receipt. Its arguments are supplied by the trusted
launcher, never constructed from the request.

## Report To A Coordinator

Save a launcher such as `report.sh` outside worker-writable paths. Replace the
paths and thread ids with values selected by the operator:

```sh
#!/bin/sh
exec /usr/bin/python3 /path/to/ferrumctl/examples/restricted-operations/adapter.py \
  report --bin /path/to/bin/codex-threadctl \
  --to COORDINATOR_THREAD_ID --from WORKER_THREAD_ID \
  --endpoint unix:///path/to/private/app-server.sock
```

The coordinator must accept direct app-server input and already be loaded.
This adapter does not load it or bypass native parent ownership. Add `--wake`
to the trusted launcher if the worker may also request an empty turn when the
coordinator is stopped. For a signal-only route, add
`--signal "A worker update is available."`; that route accepts `{}` instead
of message text.

One possible transport is a foreground `socat` listener. Use a new socket path
in an operator-controlled directory, make the launcher executable, and keep
that directory unavailable for worker writes:

```sh
umask 077
socat -T 65 \
  UNIX-LISTEN:/path/to/worker/report.sock,mode=0600,fork,max-children=8 \
  EXEC:/path/to/private/report.sh
```

The worker sends one request per connection:

```sh
printf '%s\n' '{"text":"The comparison is ready for review."}' | \
  socat -t 65 - UNIX-CONNECT:/path/to/worker/report.sock
```

```json
{"outcome":"accepted","itemId":"amsg_..."}
```

The client timeout allows the receipt to arrive after stdin closes. Listener
timeouts and child limits bound individual connections and concurrent work,
not aggregate message volume. Choose additional rate limits where needed.
Stop the listener with Ctrl-C. Confirm its processes have stopped before
removing a leftover socket; do not add an option that unlinks an existing
listener at startup. See `man socat` for transport details.

## Publish Without Reading The Stream

Create the stream from the trusted side, then use this command in another fixed
launcher with the same socket transport:

```sh
exec /usr/bin/python3 /path/to/ferrumctl/examples/restricted-operations/adapter.py \
  append --bin /path/to/bin/streamctl --stream STREAM_ID \
  --from WORKER_THREAD_ID --state /path/to/private/streams.sqlite3
```

The request is `{"text":"A finding to share."}`. The receipt contains only
`outcome: committed` and the assigned `position`. It exposes stream progress,
but no other entries, reader cursors, or database path. The worker receives
socket access, not access to SQLite. Choosing another `--state` path in a
direct CLI command separates storage; it does not enforce append-only access.

Publication does not notify anyone. A coordinator can observe this stream
independently, or a separately permitted reporting route can announce progress.

## Schedule A Self-Wake

The time-only adapter accepts `{"afterSeconds":1800}`:

```sh
exec /usr/bin/python3 /path/to/ferrumctl/examples/restricted-operations/adapter.py \
  self-wake --bin /path/to/bin/codex-wakectl --to WORKER_THREAD_ID \
  --state /path/to/private/worker-wakes.sqlite3 \
  --endpoint unix:///path/to/private/app-server.sock \
  --max-delay-seconds 86400
```

It schedules a normal event wake and returns only `outcome: scheduled` and
`jobId`. An operator-managed runner must process that exact queue. Scheduling
does not itself deliver the event; the target must be loaded when delivery
becomes possible. A dedicated queue needs its own runner arrangement; repeated
`systemd install` calls replace wakectl's single timer configuration.

The worker cannot supply input text, another target, or a command predicate.
Predicates execute with the runner's permissions, so an unrestricted runner
must not execute arbitrary worker-supplied commands. An allowed host predicate
also needs protected code and dependencies; a fixed script path alone is
insufficient if the worker can rewrite what that script executes.

## Protect The Underlying Access

Use [Codex permissions](https://developers.openai.com/codex/permissions) for
filesystem and socket configuration. Verify the actual worker boundary:

- The selected adapter socket is reachable, while real app-server endpoints,
  unrelated sockets, and private stores are not.
- Credentials, rollouts, generated memory caches, and state databases are
  unavailable through other paths. Goalctl can launch a separate app-server
  against persisted state, so blocking one socket alone is insufficient.
- The worker cannot change the launcher, adapter, backend installation, or
  their dependencies, or alter the privileged process through another interface.
- Native tools, MCP servers, approvals, and other host-side capabilities have
  compatible restrictions; shell permissions govern only their own surface.

Socket mode `0600` separates OS users, not sandboxed callers sharing a user.
Anyone who can connect can use the route with its configured author. The label
is provenance, not proof of the calling thread. Allow only the intended routes
through each worker's profile and test denied access as well as allowed access.

## Retain Receipts And Reconcile Failures

An accepted report confirms submission, a committed append confirms publication,
and a scheduled job confirms queue insertion. None proves that a model read or
acted on the content. For socket clients, read the receipt's `outcome`; a
successful transport exit alone does not establish operation success.

The adapters forward no backend diagnostics or conversation content. Explicit
rejections and `notSubmitted` outcomes are preserved. Unknown backend results
and timeouts are reported as `uncertain`; the adapter never retries.
Keep the returned receipt in the worker's own context or files.
For diagnosis, run the underlying command from the trusted side; the adapter
discards backend stderr rather than sending private errors to the worker.

An accepted report with a failed wake is `partial`: the message remains
accepted. Retry attention separately through an authorized route, not the
report. An uncertain report retains its message item id when available, so the
coordinator or operator can reconcile it without granting the worker history
access.

An append or scheduled job may commit before its receipt is lost. These
commands have no caller-supplied idempotency key; neither a new connection nor
the adapter makes repetition safe. A caller needing retry-safe submissions
must add durable request tracking and reconciliation on the trusted side.
Reader acknowledgements describe processing, not submission receipts.
