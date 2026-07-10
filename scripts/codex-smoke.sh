#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${PYTHON:-python3}
CARGO=${CARGO:-cargo}
CODEX_BIN=${CODEX_BIN:-codex}
TMP_BASE=${TMPDIR:-/tmp}

SMOKE_ROOT=""
SERVER_PID=""
SERVER_PROCESS_GROUP=0

log() {
  printf '\n==> %s\n' "$*"
}

fail() {
  printf 'codex-smoke: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  status=$?
  set +e

  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    if [[ "$SERVER_PROCESS_GROUP" == "1" ]]; then
      kill -- "-$SERVER_PID" 2>/dev/null || true
    else
      kill "$SERVER_PID" 2>/dev/null || true
    fi
    for _ in $(seq 1 20); do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      if [[ "$SERVER_PROCESS_GROUP" == "1" ]]; then
        kill -KILL -- "-$SERVER_PID" 2>/dev/null || true
      else
        kill -KILL "$SERVER_PID" 2>/dev/null || true
      fi
    fi
    wait "$SERVER_PID" 2>/dev/null || true
  fi

  if [[ -n "${SMOKE_ROOT:-}" ]]; then
    expected_prefix="${TMP_BASE%/}/ferrumctl-codex-smoke."
    if [[ "${FERRUMCTL_KEEP_SMOKE:-0}" == "1" ]]; then
      printf 'codex-smoke: kept temp dir: %s\n' "$SMOKE_ROOT" >&2
    elif [[ "$SMOKE_ROOT" == "$expected_prefix"* ]]; then
      for _ in $(seq 1 10); do
        rm -rf -- "$SMOKE_ROOT" && break
        sleep 0.1
      done
      if [[ -e "$SMOKE_ROOT" ]]; then
        printf 'codex-smoke: could not remove temp dir: %s\n' "$SMOKE_ROOT" >&2
      fi
    else
      printf 'codex-smoke: refusing to remove unexpected temp dir: %s\n' "$SMOKE_ROOT" >&2
    fi
  fi

  exit "$status"
}

trap cleanup EXIT INT TERM

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"
}

goalctl() {
  CODEX_BIN="$CODEX_BIN" PYTHONPATH="$ROOT/packages/codex-goalctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_goalctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

wakectl() {
  PYTHONPATH="$ROOT/packages/codex-threadctl/src:$ROOT/packages/codex-wakectl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_wakectl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

threadctl() {
  PYTHONPATH="$ROOT/packages/codex-threadctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_threadctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

readcov() {
  "$CARGO" run --quiet --manifest-path "$ROOT/packages/codex-readcov/Cargo.toml" -- "$@"
}

require_cmd "$PYTHON"
require_cmd "$CARGO"
require_cmd "$CODEX_BIN"

SMOKE_ROOT=$(mktemp -d "${TMP_BASE%/}/ferrumctl-codex-smoke.XXXXXX")
expected_prefix="${TMP_BASE%/}/ferrumctl-codex-smoke."
[[ "$SMOKE_ROOT" == "$expected_prefix"* ]] || fail "mktemp returned unexpected path: $SMOKE_ROOT"

export CODEX_HOME="$SMOKE_ROOT/codex-home"
export XDG_STATE_HOME="$SMOKE_ROOT/state"
mkdir -p "$CODEX_HOME" "$XDG_STATE_HOME"

inspect_thread="00000000-0000-4000-8000-000000000010"
inspect_turn="00000000-0000-4000-8000-000000000011"
inspect_rollout="$CODEX_HOME/sessions/2026/01/02/rollout-2026-01-02T03-04-05-$inspect_thread.jsonl"
mkdir -p "$(dirname "$inspect_rollout")"
"$PYTHON" - "$inspect_rollout" "$inspect_thread" "$inspect_turn" "$SMOKE_ROOT" <<'PY'
import json
import sys

rollout, thread_id, turn_id, cwd = sys.argv[1:]
timestamp = "2026-01-02T03:04:05Z"
events = [
    {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": thread_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "originator": "ferrumctl-codex-smoke",
            "cli_version": "0.0.0",
            "source": "cli",
            "thread_source": "user",
            "model_provider": "openai",
        },
    },
    {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "turn_started",
            "turn_id": turn_id,
            "started_at": 1767323045,
            "model_context_window": 200000,
        },
    },
    {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": "user",
            "role": "user",
            "content": [{"type": "input_text", "text": "Smoke request."}],
        },
    },
    {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": "Smoke request.",
            "kind": "plain",
        },
    },
    {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "id": "answer",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Smoke complete."}],
            "phase": "final_answer",
        },
    },
    {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "agent_message",
            "message": "Smoke complete.",
            "phase": "final_answer",
        },
    },
    {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "turn_complete",
            "turn_id": turn_id,
            "last_agent_message": "Smoke complete.",
            "completed_at": 1767323047,
            "duration_ms": 2000,
        },
    },
    {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 12000,
                    "cached_input_tokens": 10000,
                    "output_tokens": 345,
                    "reasoning_output_tokens": 45,
                    "total_tokens": 12345,
                },
                "last_token_usage": {
                    "input_tokens": 12000,
                    "cached_input_tokens": 10000,
                    "output_tokens": 345,
                    "reasoning_output_tokens": 45,
                    "total_tokens": 12345,
                },
                "model_context_window": 200000,
            },
            "rate_limits": None,
        },
    },
]

with open(rollout, "w", encoding="utf-8") as handle:
    for event in events:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
PY

log "Codex version"
codex_version=$("$CODEX_BIN" --version)
printf '%s\n' "$codex_version"
codex_semver=$(printf '%s\n' "$codex_version" | sed -n 's/^codex-cli \([0-9][0-9.]*\)$/\1/p')

parser_tag=$(sed -n 's/.*tag = "\(rust-v[^"]*\)".*/\1/p' "$ROOT/packages/codex-readcov/Cargo.toml")
if [[ -n "$parser_tag" ]]; then
  printf 'codex-readcov parser dependency: codex-shell-command %s\n' "$parser_tag"
fi
log "goalctl stdio app-server compatibility"
missing_thread="00000000-0000-4000-8000-000000000001"
if goalctl --json --timeout 5 get "$missing_thread" >"$SMOKE_ROOT/goal.out" 2>"$SMOKE_ROOT/goal.err"; then
  fail "expected missing temporary thread to fail"
fi
grep -Eq 'thread not found|invalid thread id' "$SMOKE_ROOT/goal.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/goal.err" >&2
  fail "unexpected goalctl error"
}
printf 'goalctl reached app-server and got expected temporary-thread error\n'

if goalctl --json --timeout 5 update "$missing_thread" \
  --clear-token-budget >"$SMOKE_ROOT/goal-clear.out" 2>"$SMOKE_ROOT/goal-clear.err"; then
  fail "expected missing token-budget thread to fail"
fi
grep -Eq 'thread not found|invalid thread id' "$SMOKE_ROOT/goal-clear.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/goal-clear.err" >&2
  fail "unexpected token-budget clear error"
}
printf 'goalctl token-budget removal reached app-server\n'

log "threadctl and wakectl unix app-server compatibility"
if command -v setsid >/dev/null 2>&1; then
  setsid "$CODEX_BIN" app-server --listen unix:// >"$SMOKE_ROOT/app-server.out" 2>"$SMOKE_ROOT/app-server.err" &
  SERVER_PID=$!
  SERVER_PROCESS_GROUP=1
else
  "$CODEX_BIN" app-server --listen unix:// >"$SMOKE_ROOT/app-server.out" 2>"$SMOKE_ROOT/app-server.err" &
  SERVER_PID=$!
fi

socket="$CODEX_HOME/app-server-control/app-server-control.sock"
for _ in $(seq 1 100); do
  [[ -S "$socket" ]] && break
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    sed -n '1,80p' "$SMOKE_ROOT/app-server.err" >&2
    fail "app-server exited before socket was ready"
  fi
  sleep 0.1
done
[[ -S "$socket" ]] || {
  sed -n '1,80p' "$SMOKE_ROOT/app-server.err" >&2
  fail "app-server socket was not created: $socket"
}

threadctl --timeout 5 loaded >"$SMOKE_ROOT/loaded.out"
printf 'threadctl reached app-server; loaded threads: %s\n' "$(wc -l <"$SMOKE_ROOT/loaded.out")"

threadctl --timeout 5 inspect "$inspect_thread" \
  --no-previous >"$SMOKE_ROOT/inspect.out"
grep -q $'^latest\tcompleted\t'"$inspect_turn" "$SMOKE_ROOT/inspect.out" || {
  sed -n '1,40p' "$SMOKE_ROOT/inspect.out" >&2
  fail "threadctl full inspection omitted completed turn"
}
grep -Fq $'view=full\tduration=2000ms' "$SMOKE_ROOT/inspect.out" || {
  sed -n '1,40p' "$SMOKE_ROOT/inspect.out" >&2
  fail "threadctl full inspection omitted turn timing"
}
grep -Fqx $'agentMessage:final_answer\t"Smoke complete."' "$SMOKE_ROOT/inspect.out" || {
  sed -n '1,40p' "$SMOKE_ROOT/inspect.out" >&2
  fail "threadctl full inspection omitted final response"
}
grep -q $'^context\tused=12345\twindow=200000\tleft=100%' "$SMOKE_ROOT/inspect.out" || {
  sed -n '1,40p' "$SMOKE_ROOT/inspect.out" >&2
  fail "threadctl inspection omitted context usage"
}

threadctl --timeout 5 --json inspect "$inspect_thread" \
  --brief --no-previous >"$SMOKE_ROOT/inspect-brief.json"
"$PYTHON" - "$SMOKE_ROOT/inspect-brief.json" "$inspect_turn" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    inspection = json.load(handle)
turn = inspection["latestTurn"]
assert turn["id"] == sys.argv[2]
assert turn["status"] == "completed"
assert turn["itemsView"] == "summary"
assert turn["startedAt"] == 1767323045
assert turn["completedAt"] == 1767323047
assert turn["durationMs"] == 2000
assert turn["items"][-1]["text"] == "Smoke complete."
assert inspection["context"]["usedTokens"] == 12345
assert inspection["context"]["windowTokens"] == 200000
assert inspection["context"]["percentLeft"] == 100
PY
printf 'threadctl inspected persisted full and summary turn history\n'

threadctl --timeout 5 --json messages "$inspect_thread" \
  --limit 2 >"$SMOKE_ROOT/messages.json"
"$PYTHON" - "$SMOKE_ROOT/messages.json" "$SMOKE_ROOT/message-locator" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    messages = json.load(handle)["messages"]
assert [message["text"] for message in messages] == ["Smoke request.", "Smoke complete."]
message = messages[-1]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write(f"{message['turnId']}\t{message['itemId']}\n")
PY
IFS=$'\t' read -r message_turn message_item <"$SMOKE_ROOT/message-locator"
threadctl --timeout 5 message "$inspect_thread" "$message_turn" "$message_item" \
  >"$SMOKE_ROOT/message.out"
grep -Fqx 'Smoke complete.' "$SMOKE_ROOT/message.out" || {
  sed -n '1,20p' "$SMOKE_ROOT/message.out" >&2
  fail "threadctl did not retrieve the selected message"
}
printf 'threadctl listed and retrieved materialized messages\n'

threadctl --timeout 5 --json resume "$inspect_thread" >"$SMOKE_ROOT/resume.json"
"$PYTHON" - "$SMOKE_ROOT/resume.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["threadId"] == sys.argv[2]
assert result["status"]["type"] == "idle"
PY
printf 'threadctl resumed persisted state without starting a turn\n'

if wakectl --timeout 5 add stop "$missing_thread" \
  --to "$missing_thread" "smoke" >"$SMOKE_ROOT/turns.out" 2>"$SMOKE_ROOT/turns.err"; then
  fail "expected missing stop-watch thread to fail"
fi
grep -Eq 'thread not found|thread not loaded' "$SMOKE_ROOT/turns.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/turns.err" >&2
  fail "unexpected thread/turns/list error"
}
printf 'wakectl reached paged turn history and got expected temporary-thread error\n'

if threadctl --timeout 5 --json interrupt "$missing_thread" \
  "00000000-0000-4000-8000-000000000002" \
  >"$SMOKE_ROOT/interrupt.out" 2>"$SMOKE_ROOT/interrupt.err"; then
  fail "expected missing interrupt thread to fail"
fi
grep -Eq 'thread not found|thread (is )?not loaded|invalid thread id' "$SMOKE_ROOT/interrupt.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/interrupt.err" >&2
  fail "unexpected turn/interrupt error"
}
printf 'threadctl reached turn interruption API\n'

log "readcov rollout parser compatibility"
project="$SMOKE_ROOT/project"
rollout="$SMOKE_ROOT/rollout-smoke.jsonl"
mkdir -p "$project/src"
"$PYTHON" - "$rollout" "$project" <<'PY'
import json
import sys

rollout, project = sys.argv[1], sys.argv[2]
events = [
    {
        "type": "session_meta",
        "payload": {
            "id": "00000000-0000-4000-8000-000000000002",
            "cwd": project,
        },
    },
    {
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "name": "exec",
            "input": (
                "const result = await tools.exec_command({"
                "cmd: \"cat src/a.rs && sed -n '1,5p' src/b.rs\","
                f"workdir: {json.dumps(project)}"
                "}); text(result.output);"
            ),
        },
    },
]

with open(rollout, "w", encoding="utf-8") as handle:
    for event in events:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
PY

readcov top "$rollout" "$project/src" --paths-only --limit 0 >"$SMOKE_ROOT/readcov.out"
grep -qx 'src/a.rs' "$SMOKE_ROOT/readcov.out" || fail "readcov did not report src/a.rs"
grep -qx 'src/b.rs' "$SMOKE_ROOT/readcov.out" || fail "readcov did not report src/b.rs"
printf 'readcov parsed the current exec tool envelope\n'

if [[ -n "$codex_semver" && -n "$parser_tag" && "$parser_tag" != "rust-v$codex_semver" ]]; then
  fail "codex-readcov parser tag $parser_tag does not match codex-cli $codex_semver"
fi

printf '\ncodex smoke passed\n'
