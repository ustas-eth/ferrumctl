<!-- Generated from docs/host-automation.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Host Automation

These examples use ferrumctl from shell scripts, schedulers, or another coding
agent. Humans and scripts can call installed commands directly. An agent should
normally use only commands whose skills are available unless the user
explicitly requests another installed command.

## Capacity Gate

Apply a threshold only when the workflow already has a capacity policy:

```sh
codex-limitctl list
codex-limitctl test codex --window 7d --remaining-at-least 20
```

`test` exits `0` when true, `1` when false, and `2` when the observation is
unavailable. Preserve all three outcomes. A successful gate is a point-in-time
observation, not a capacity reservation.

When scheduled input is available and the selected window includes a renewal
time, a sleeping coordinator can wake then and evaluate the policy again:

```sh
SELF=${CODEX_THREAD_ID:?CODEX_THREAD_ID is not set}
RENEWS_AT=$(codex-limitctl list codex --window 7d --json |
  jq -er '.windows[0].resetsAt | todateiso8601')
codex-wakectl add time --at "$RENEWS_AT" --to "$SELF" \
  "Automated event: Subscription window renewed."
```

For a short wait that may become ready before renewal, the same policy can be a
queued command predicate:

```sh
codex-wakectl add cmd --to "$SELF" \
  "Automated event: Subscription capacity is available." -- \
  codex-limitctl test codex --window 7d --remaining-at-least 20
```

Both false exit `1` and unavailable exit `2` remain pending. Keep the inner
timeout below the runner timeout and add a separate review deadline when
persistent observation failure must not wait indefinitely.

## Host Conditions

A queued command condition is a repeated probe, not the scheduled work:

```sh
codex-wakectl add cmd --to THREAD_ID \
  "Automated event: Input is ready." -- test -f done.txt
```

Run the queue through the recurring user timer:

```sh
codex-wakectl systemd install --interval 30s
```

Stateful detection, diagnostics, or expensive polling belongs in a separate
host process. Persist its result, then let the wake predicate test that stable
state. Add an independent review deadline when a broken watcher would otherwise
require user intervention.

## External Manager

Another coding agent or host process can manage Codex sessions when it has the
same Codex home, their thread ids, and the app-server endpoint that owns live
execution:

```sh
export CODEX_HOME=/path/to/codex-home
ENDPOINT=unix:///path/to/codex.sock
WORKER=worker-thread-id

codex-threadctl --endpoint "$ENDPOINT" loaded
codex-threadctl --endpoint "$ENDPOINT" inspect "$WORKER"
codex-goalctl replace "$WORKER" "Work from this external assignment."
codex-threadctl --endpoint "$ENDPOINT" start "$WORKER" \
  "From coordinator: A goal was assigned. Call get_goal and proceed."
```

The manager owns socket discovery, runner lifecycle, saved identifiers, and
cleanup. Goalctl reaches persisted state through its own short-lived server;
live control still belongs to the selected shared endpoint.

## Scripted Read Audit

Snapshots make a thread's read interval available to later host processing:

```sh
codex-readcov snapshot "$WORKER" > before.json
# work happens here
codex-readcov snapshot "$WORKER" > after.json
codex-readcov delta before.json --to after.json \
  --paths-only --limit 0 | sort > read.txt
```

Use ordinary set tools for comparison or negative coverage. Build every input
in the snapshot cwd namespace; readcov supplies recorded read paths, not the
expected file universe.

Use structured output and preserve exact thread, turn, item, stream, and job
identifiers whenever another program will make the next decision.
