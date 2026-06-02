# Codex Wake Control Notes

These notes capture the current understanding of how an external process can
wake or drive Codex CLI sessions.

This is not a design for `codex-goalctl`. Goal state and wake/input delivery
are separate concerns:

- `codex-goalctl` reads and writes persisted thread goals.
- A wake tool would deliver an input turn or keystrokes to a running session.

## What Worked

### Shared app-server TUI wake

A Codex TUI launched against a shared app-server can be woken through that
same app-server.

Server:

```sh
codex app-server --listen unix://
```

TUI:

```sh
codex --remote unix://
```

Observed working thread:

```text
019e61c3-2fdb-7670-bf2e-05f214381059
```

The external client called `turn/start` through the Unix socket. The live TUI
updated immediately and showed the model response.

Important transport detail: the Unix socket is WebSocket-over-UDS, not JSONL.
The HTTP upgrade path used by Codex is:

```text
ws://localhost/rpc
```

With Python `websockets`, the working connection shape was:

```python
websockets.unix_connect(
    "/home/ustas/.codex/app-server-control/app-server-control.sock",
    uri="ws://localhost/rpc",
    compression=None,
    user_agent_header=None,
)
```

The `compression=None` and `user_agent_header=None` pieces mattered in the
local experiment. The default Python WebSocket handshake was closed by the
server before an HTTP response.

Minimal request flow:

1. Connect to the Unix socket with WebSocket upgrade at `ws://localhost/rpc`.
2. Send `initialize`.
3. Send `initialized`.
4. Call `thread/loaded/list` to discover loaded thread ids.
5. Call `turn/start` with the target `threadId` and text input.

The `turn/start` input item shape that worked:

```json
{
  "threadId": "THREAD_ID",
  "input": [
    {
      "type": "text",
      "text": "Wake message here.",
      "textElements": []
    }
  ]
}
```

## What Did Not Work

### Default embedded TUI app-server access

The normal Codex TUI runs an embedded in-process app-server by default. We did
not find an externally reachable socket, daemon control socket, remote-control
enrollment, or listener for that embedded server.

Starting a separate app-server and calling `thread/resume` plus `turn/start`
against an existing embedded-TUI thread did run a turn and append to the
rollout, but the live TUI did not repaint. The TUI only reflected the external
turn later after resume/reload.

That path creates split-brain risk:

- stale visible UI
- separate in-memory context
- possible config mismatch
- different approval and sandbox settings
- confusing transcript state

Conclusion: do not use a separate app-server as a live wake path for an
already-running embedded TUI.

### `codex app-server proxy` as JSONL bridge

`codex app-server proxy` is not a JSONL-to-WebSocket translator. It proxies raw
bytes to the Unix socket. A client still has to perform the WebSocket HTTP
upgrade and send WebSocket frames.

## What May Work

### Tmux or PTY wake for default TUI sessions

For default embedded TUI sessions, terminal input injection is still the most
reliable live wake mechanism found so far.

Possible first version:

```sh
codex-wakectl send --pane %129 "Scheduled wake: call get_goal and continue if useful."
```

This uses the same path as a human typing into the TUI, so the live UI,
session config, approvals, sandbox, and in-memory state remain aligned.

Open questions:

- how to handle a partially typed prompt
- whether to default to clearing the prompt first
- how to map a thread id back to a tmux pane safely
- whether to require explicit `--pane` in v1

### App-server wake for shared daemon or remote sessions

For sessions launched with `codex --remote unix://`, a wake tool can call
`turn/start` through the shared app-server.

Possible first version:

```sh
codex-wakectl turn --thread THREAD_ID "Scheduled wake: call get_goal and continue if useful."
```

This should only be advertised for daemon/shared/remote sessions. It should
not claim to wake ordinary embedded TUI sessions.

Possible discovery helpers:

```sh
codex-wakectl loaded
codex-wakectl turn --latest "message"
```

Risks to handle:

- loaded thread selection when multiple remote TUIs are connected
- active turn conflicts
- approvals or server requests during the turn
- app-server version drift
- connection liveness and retry behavior

### Loopback WebSocket app-server

`codex app-server --listen ws://127.0.0.1:PORT` worked as a shared app-server.
It can likely support the same `turn/start` workflow for a TUI launched with:

```sh
codex --remote ws://127.0.0.1:PORT
```

This is less attractive than Unix sockets for local-only control, but it may
be useful where Unix socket paths are awkward.

### Headless app-server worker

`codex app-server --listen stdio://` remains useful for scripts that own the
app-server process. It is not a way to wake an existing TUI.

This mode can support controlled background turns if the client handles:

- initialization
- `thread/start` or `thread/resume`
- `turn/start`
- streaming notifications
- approval/server-request messages
- shutdown

### Remote control

Codex has remote-control code paths and daemon management commands. We did not
use them in the successful wake experiment.

The managed daemon command failed on this host because the standalone Codex
installer layout was missing:

```text
managed standalone Codex install not found at ~/.codex/packages/standalone/current/codex
```

Remote control may still be relevant for a more standard long-running setup,
but it needs a separate experiment with the expected standalone install.

## Current Design Bias

Keep a wake utility small and explicit.

Suggested v1 shape:

```sh
codex-wakectl send --pane %129 "message"
codex-wakectl loaded
codex-wakectl turn --thread THREAD_ID "message"
```

Where:

- `send` is terminal/tmux based and intended for default TUI sessions.
- `turn` is app-server based and intended for shared daemon/remote sessions.
- scheduling is left to cron/systemd timers at first.

Avoid hiding the backend choice. A wake through tmux and a wake through
app-server have different semantics and failure modes.
