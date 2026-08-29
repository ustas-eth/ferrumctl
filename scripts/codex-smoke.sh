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

limitctl() {
  CODEX_BIN="$CODEX_BIN" PYTHONPATH="$ROOT/packages/codex-limitctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_limitctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

streamctl() {
  PYTHONPATH="$ROOT/packages/streamctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from streamctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

wakectl() {
  PYTHONPATH="$ROOT/packages/codex-threadctl/src:$ROOT/packages/codex-wakectl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_wakectl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

threadctl() {
  PYTHONPATH="$ROOT/packages/codex-threadctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_threadctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
}

memoryctl() {
  PYTHONPATH="$ROOT/packages/codex-threadctl/src:$ROOT/packages/codex-memoryctl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_memoryctl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
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
agent_thread="00000000-0000-4000-8000-000000000012"
agent_rollout="$CODEX_HOME/sessions/2026/01/02/rollout-2026-01-02T03-03-00-$agent_thread.jsonl"
memory_thread="00000000-0000-4000-8000-000000000013"
memory_rollout="$CODEX_HOME/sessions/2026/01/02/rollout-2026-01-02T03-02-00-$memory_thread.jsonl"
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
        "type": "turn_context",
        "payload": {
            "model": "gpt-smoke",
            "service_tier": "default",
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
            "rate_limits": {
                "limit_id": "codex",
                "primary": {
                    "used_percent": 11,
                    "window_minutes": 10080,
                    "resets_at": 1767830400,
                },
                "secondary": None,
            },
        },
    },
]

with open(rollout, "w", encoding="utf-8") as handle:
    for event in events:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
PY

"$PYTHON" - "$memory_rollout" "$memory_thread" "$SMOKE_ROOT" <<'PY'
import json
import sys

rollout, thread_id, cwd = sys.argv[1:]
timestamp = "2026-01-02T03:02:00Z"
memory = {
    "type": "compaction",
    "id": "cmp_smoke",
    "encrypted_content": "opaque-memory-smoke",
    "internal_chat_message_metadata_passthrough": {"turn_id": "memory-turn"},
}
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
        "type": "turn_context",
        "payload": {"model": "gpt-smoke", "service_tier": "default"},
    },
    {
        "timestamp": timestamp,
        "type": "compacted",
        "payload": {
            "message": "",
            "replacement_history": [memory],
            "window_number": 1,
            "first_window_id": "00000000-0000-4000-8000-000000000014",
            "previous_window_id": None,
            "window_id": "00000000-0000-4000-8000-000000000014",
        },
    },
]

with open(rollout, "w", encoding="utf-8") as handle:
    for event in events:
        handle.write(json.dumps(event, separators=(",", ":")) + "\n")
PY

"$PYTHON" - "$agent_rollout" "$agent_thread" "$inspect_thread" "$SMOKE_ROOT" <<'PY'
import json
import sys

rollout, thread_id, parent_id, cwd = sys.argv[1:]
timestamp = "2026-01-02T03:03:00Z"
event = {
    "timestamp": timestamp,
    "type": "session_meta",
    "payload": {
        "session_id": parent_id,
        "id": thread_id,
        "parent_thread_id": parent_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "originator": "ferrumctl-codex-smoke",
        "cli_version": "0.0.0",
        "source": {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": parent_id,
                    "depth": 1,
                    "agent_path": "/root/reviewer",
                    "agent_nickname": "Reviewer",
                    "agent_role": "reviewer",
                }
            }
        },
        "thread_source": "subagent",
        "agent_nickname": "Reviewer",
        "agent_path": "/root/reviewer",
        "agent_role": "reviewer",
        "model_provider": "openai",
        "history_mode": "legacy",
        "multi_agent_version": "v2",
    },
}

with open(rollout, "w", encoding="utf-8") as handle:
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

log "app-server schema compatibility"
schema_dir="$SMOKE_ROOT/app-server-schema"
"$CODEX_BIN" app-server generate-json-schema --out "$schema_dir" >/dev/null
"$PYTHON" - "$schema_dir/ClientRequest.json" \
  "$schema_dir/codex_app_server_protocol.v2.schemas.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    requests = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    protocol = json.load(handle)

def request_definitions(value, method):
    if isinstance(value, dict):
        properties = value.get("properties", {})
        methods = properties.get("method", {}).get("enum", [])
        if method in methods:
            yield value
        for child in value.values():
            yield from request_definitions(child, method)
    elif isinstance(value, list):
        for child in value:
            yield from request_definitions(child, method)


rate_limit_requests = list(request_definitions(requests, "account/rateLimits/read"))
assert len(rate_limit_requests) == 1
request = rate_limit_requests[0]
assert set(request["required"]) == {"id", "method"}
assert request["properties"]["params"] == {"type": "null"}

usage_requests = list(request_definitions(requests, "account/usage/read"))
assert len(usage_requests) == 1
request = usage_requests[0]
assert set(request["required"]) == {"id", "method"}
usage_params = request["properties"]["params"]
if usage_params != {"type": "null"}:
    assert {
        entry.get("$ref") or entry.get("type")
        for entry in usage_params["anyOf"]
    } == {"#/definitions/GetAccountTokenUsageParams", "null"}

definitions = protocol["definitions"]
thread = definitions["Thread"]["properties"]
assert {"parentThreadId", "source", "status"} <= set(thread)

spawn_source = next(
    entry
    for entry in definitions["SubAgentSource"]["oneOf"]
    if entry.get("title") == "ThreadSpawnSubAgentSource"
)
spawn = spawn_source["properties"]["thread_spawn"]["properties"]
assert {"parent_thread_id", "depth", "agent_path"} <= set(spawn)

subagent_activity = next(
    entry
    for entry in definitions["ThreadItem"]["oneOf"]
    if entry.get("title") == "SubAgentActivityThreadItem"
)
assert {"agentThreadId", "agentPath"} <= set(
    subagent_activity["properties"]
)

response = definitions["GetAccountRateLimitsResponse"]
snapshot = definitions["RateLimitSnapshot"]["properties"]
window = definitions["RateLimitWindow"]["properties"]
assert response["type"] == "object"
assert response["required"] == ["rateLimits"]
assert {"rateLimits", "rateLimitsByLimitId"} <= set(response["properties"])
assert response["properties"]["rateLimits"]["allOf"] == [
    {"$ref": "#/definitions/RateLimitSnapshot"}
]
assert set(response["properties"]["rateLimitsByLimitId"]["type"]) == {"object", "null"}
assert response["properties"]["rateLimitsByLimitId"]["additionalProperties"] == {
    "$ref": "#/definitions/RateLimitSnapshot"
}
assert {"limitId", "limitName", "planType", "primary", "secondary"} <= set(snapshot)
assert set(snapshot["limitId"]["type"]) == {"string", "null"}
assert set(snapshot["limitName"]["type"]) == {"string", "null"}
assert definitions["PlanType"]["type"] == "string"
for field in ("primary", "secondary"):
    assert {entry.get("$ref") or entry.get("type") for entry in snapshot[field]["anyOf"]} == {
        "#/definitions/RateLimitWindow",
        "null",
    }
assert {"usedPercent", "windowDurationMins", "resetsAt"} <= set(window)
assert window["usedPercent"]["type"] == "integer"
assert set(window["windowDurationMins"]["type"]) == {"integer", "null"}
assert set(window["resetsAt"]["type"]) == {"integer", "null"}

usage = definitions["GetAccountTokenUsageResponse"]["properties"]
daily = usage["dailyUsageBuckets"]
assert set(daily["type"]) == {"array", "null"}
assert daily["items"] == {"$ref": "#/definitions/AccountTokenUsageDailyBucket"}
bucket = definitions["AccountTokenUsageDailyBucket"]
assert {"startDate", "tokens"} <= set(bucket["required"])
assert bucket["properties"]["startDate"]["type"] == "string"
assert bucket["properties"]["tokens"]["type"] == "integer"

inject_requests = list(request_definitions(requests, "thread/inject_items"))
assert len(inject_requests) == 1
inject = definitions["ThreadInjectItemsParams"]
assert set(inject["required"]) == {"threadId", "items"}
assert inject["properties"]["items"]["type"] == "array"

turn_start = definitions["TurnStartParams"]
assert set(turn_start["required"]) == {"threadId", "input"}
assert turn_start["properties"]["input"]["type"] == "array"

response_items = definitions["ResponseItem"]["oneOf"]
agent_message = next(
    item for item in response_items if item.get("title") == "AgentMessageResponseItem"
)
assert set(agent_message["required"]) == {"type", "author", "recipient", "content"}
assert agent_message["properties"]["type"]["enum"] == ["agent_message"]
PY
printf 'required account, agent-tree, notification, and turn-start shapes are present\n'

if limitctl --timeout 5 list \
  >"$SMOKE_ROOT/limit.out" 2>"$SMOKE_ROOT/limit.err"; then
  fail "expected isolated account read to require authentication"
else
  limit_status=$?
fi
[[ "$limit_status" == "2" ]] || {
  sed -n '1,40p' "$SMOKE_ROOT/limit.err" >&2
  fail "limitctl authentication failure used exit $limit_status instead of 2"
}
grep -Eq '^codex-limitctl: app-server error [-0-9]+: .*authentication' \
  "$SMOKE_ROOT/limit.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/limit.err" >&2
  fail "unexpected limitctl authentication error"
}
printf 'limitctl reached account API and preserved operational exit status\n'

if limitctl usage --timeout 5 \
  >"$SMOKE_ROOT/usage.out" 2>"$SMOKE_ROOT/usage.err"; then
  fail "expected isolated account usage read to require authentication"
else
  usage_status=$?
fi
[[ "$usage_status" == "2" ]] || {
  sed -n '1,40p' "$SMOKE_ROOT/usage.err" >&2
  fail "limitctl usage authentication failure used exit $usage_status instead of 2"
}
grep -Eq '^codex-limitctl: app-server error [-0-9]+: .*authentication' \
  "$SMOKE_ROOT/usage.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/usage.err" >&2
  fail "unexpected limitctl usage authentication error"
}
printf 'limitctl reached account usage API and preserved operational exit status\n'

limitctl history codex --window 7d --since 2026-01-01 --codex-home "$CODEX_HOME" \
  >"$SMOKE_ROOT/history.out"
grep -Fq "thread=$inspect_thread" "$SMOKE_ROOT/history.out" ||
  fail "limitctl history did not parse the rollout rate-limit record"

limitctl activity --since 2026-01-01 --codex-home "$CODEX_HOME" \
  >"$SMOKE_ROOT/activity.out"
grep -Fq "$inspect_thread" "$SMOKE_ROOT/activity.out" ||
  fail "limitctl activity omitted the rollout thread"
grep -Fq 'model=gpt-smoke' "$SMOKE_ROOT/activity.out" ||
  fail "limitctl activity omitted the rollout model"
grep -Fq 'tokens=12345' "$SMOKE_ROOT/activity.out" ||
  fail "limitctl activity did not parse cumulative token usage"
printf 'limitctl parsed rollout history and thread activity\n'

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

log "streamctl SQLite state transitions"
stream=$(streamctl create --label smoke)
CODEX_THREAD_ID=a streamctl append "$stream" "first" \
  >"$SMOKE_ROOT/stream-position.out"
grep -Fqx '1' "$SMOKE_ROOT/stream-position.out" ||
  fail "streamctl did not assign the first position"
streamctl --json append "$stream" --author b --reply-to 1 "second" \
  >"$SMOKE_ROOT/stream-append.json"
CODEX_THREAD_ID=b streamctl --json list "$stream" --limit 0 \
  >"$SMOKE_ROOT/stream-list.json"
"$PYTHON" - "$SMOKE_ROOT/stream-list.json" "$stream" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["streamId"] == sys.argv[2]
assert result["lastPosition"] == 2
assert [entry["position"] for entry in result["entries"]] == [1, 2]
assert result["entries"][1]["replyTo"] == 1
PY
CODEX_THREAD_ID=b streamctl ack "$stream" --through 2 \
  >"$SMOKE_ROOT/stream-ack.out"
CODEX_THREAD_ID=b streamctl list "$stream" >"$SMOKE_ROOT/stream-unread.out"
[[ ! -s "$SMOKE_ROOT/stream-unread.out" ]] ||
  fail "streamctl returned acknowledged entries"
printf 'streamctl persisted ordered entries and reader acknowledgement\n'

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

threadctl --timeout 5 --json list --limit 1 >"$SMOKE_ROOT/thread-list.json"
threadctl --timeout 5 --json list --parent "$inspect_thread" --limit 1 \
  >"$SMOKE_ROOT/child-list.json"
"$PYTHON" - "$SMOKE_ROOT/thread-list.json" "$SMOKE_ROOT/child-list.json" \
  "$inspect_thread" "$agent_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    threads = json.load(handle)["threads"]
with open(sys.argv[2], encoding="utf-8") as handle:
    children = json.load(handle)["threads"]
assert [thread["id"] for thread in threads] == [sys.argv[3]]
assert [thread["id"] for thread in children] == [sys.argv[4]]
assert children[0]["parentThreadId"] == sys.argv[3]
PY
printf 'threadctl listed persisted threads and selected a v2 child by parent\n'

threadctl --timeout 5 --json search "Smoke complete" --limit 1 \
  >"$SMOKE_ROOT/thread-search.json"
"$PYTHON" - "$SMOKE_ROOT/thread-search.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    threads = json.load(handle)["threads"]
assert [thread["id"] for thread in threads] == [sys.argv[2]]
assert "Smoke complete" in threads[0]["snippet"]
PY
printf 'threadctl searched persisted thread content and returned a snippet\n'

threadctl --timeout 5 --json agents "$agent_thread" \
  >"$SMOKE_ROOT/agents.json"
threadctl --timeout 5 --json agents /root/reviewer --tree "$agent_thread" \
  >"$SMOKE_ROOT/agents-by-path.json"
threadctl --timeout 5 resolve /root/reviewer --tree "$agent_thread" \
  >"$SMOKE_ROOT/resolved-agent.out"
threadctl --timeout 5 --json status /root/reviewer --tree "$agent_thread" \
  >"$SMOKE_ROOT/agent-status.json"
"$PYTHON" - "$SMOKE_ROOT/agents.json" "$SMOKE_ROOT/agents-by-path.json" \
  "$SMOKE_ROOT/agent-status.json" "$inspect_thread" "$agent_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    tree = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    tree_by_path = json.load(handle)
with open(sys.argv[3], encoding="utf-8") as handle:
    status = json.load(handle)

root_id, agent_id = sys.argv[4:]
assert tree["rootThreadId"] == root_id
assert tree_by_path == tree
assert [(entry["agentPath"], entry["threadId"]) for entry in tree["agents"]] == [
    ("/root", root_id),
    ("/root/reviewer", agent_id),
]
child = tree["agents"][1]
assert child["parentThreadId"] == root_id
assert child["depth"] == 1
assert child["inputOwner"] == "parent"
assert status["threadId"] == agent_id
assert status["agentPath"] == "/root/reviewer"
assert status["inputOwner"] == "parent"
PY
grep -Fqx "$agent_thread" "$SMOKE_ROOT/resolved-agent.out" ||
  fail "threadctl did not resolve the v2 agent path"
printf 'threadctl reconstructed, resolved, and inspected a persisted v2 agent tree\n'

agent_watch=$(wakectl --timeout 5 add goal /root/reviewer --status complete \
  --to /root --tree "$agent_thread")
wakectl --json list >"$SMOKE_ROOT/agent-watch.json"
"$PYTHON" - "$SMOKE_ROOT/agent-watch.json" "$agent_watch" \
  "$inspect_thread" "$agent_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    jobs = json.load(handle)["jobs"]
job = next(entry for entry in jobs if entry["id"] == sys.argv[2])
assert job["condition"]["threadId"] == sys.argv[4]
assert job["targetThreadId"] == sys.argv[3]
PY
wakectl cancel "$agent_watch" >"$SMOKE_ROOT/agent-watch-cancel.out"

if wakectl --timeout 5 add time --after 1h --to /root/reviewer \
  --tree "$agent_thread" >"$SMOKE_ROOT/agent-target.out" \
  2>"$SMOKE_ROOT/agent-target.err"; then
  fail "expected a v2 child wake target to be rejected"
fi
grep -Fq 'cannot receive scheduled input' "$SMOKE_ROOT/agent-target.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/agent-target.err" >&2
  fail "wakectl did not explain v2 parent-owned delivery"
}
printf 'wakectl observed a v2 child and stored its parent as the delivery target\n'

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

threadctl --timeout 5 --json items "$inspect_thread" \
  --limit 0 >"$SMOKE_ROOT/items.json"
"$PYTHON" - "$SMOKE_ROOT/items.json" "$SMOKE_ROOT/item-boundary" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
assert payload["view"] == "materialized"
assert payload["backend"] == "thread/turns/list"
assert [item["type"] for item in payload["items"]] == [
    "userMessage",
    "agentMessage",
]
boundary = payload["items"][0]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write(f"{boundary['turnId']}\t{boundary['itemId']}\n")
PY
IFS=$'\t' read -r boundary_turn boundary_item <"$SMOKE_ROOT/item-boundary"
threadctl --timeout 5 --json messages "$inspect_thread" \
  --after "$boundary_turn" "$boundary_item" --limit 0 \
  >"$SMOKE_ROOT/ranged-messages.json"
"$PYTHON" - "$SMOKE_ROOT/ranged-messages.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    messages = json.load(handle)["messages"]
assert [message["text"] for message in messages] == ["Smoke complete."]
PY
printf 'threadctl listed compact items and selected an exclusive range\n'

goalctl replace "$inspect_thread" "Smoke-test guarded resume." \
  >"$SMOKE_ROOT/resume-goal.out"
if threadctl --timeout 5 resume "$inspect_thread" \
  >"$SMOKE_ROOT/resume-guard.out" 2>"$SMOKE_ROOT/resume-guard.err"; then
  fail "expected resume with an active goal to require explicit continuation"
fi
grep -Fq -- '--continue-goal' "$SMOKE_ROOT/resume-guard.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/resume-guard.err" >&2
  fail "threadctl did not explain guarded goal continuation"
}
goalctl clear "$inspect_thread" >"$SMOKE_ROOT/resume-goal-clear.out"

threadctl --timeout 5 --json resume "$inspect_thread" --continue-goal \
  >"$SMOKE_ROOT/resume.json"
"$PYTHON" - "$SMOKE_ROOT/resume.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["threadId"] == sys.argv[2]
assert result["status"]["type"] == "idle"
assert result["goalContinuationAllowed"] is True
PY
printf 'threadctl required explicit goal-continuation acknowledgement for resume\n'

wake_job=$(wakectl --timeout 5 add time --after 1s --to "$inspect_thread")
sleep 1.1
wakectl --timeout 5 --json run >"$SMOKE_ROOT/wakectl-run.json"
wakectl --json list --all >"$SMOKE_ROOT/wakectl-all.json"
"$PYTHON" - "$SMOKE_ROOT/wakectl-run.json" "$SMOKE_ROOT/wakectl-all.json" \
  "$wake_job" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    run = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    jobs = json.load(handle)["jobs"]
fired = next(item for item in run["fired"] if item["id"] == sys.argv[3])
job = next(item for item in jobs if item["id"] == sys.argv[3])
assert fired["delivery"] == "eventStarted"
assert fired["turnId"]
assert job["action"] == {"type": "event"}
assert job["lastEventItemId"] == f"amsg_wake_{sys.argv[3]}_1"
assert job["lastTurnId"] == fired["turnId"]
assert job["status"] == "fired"
PY
printf 'wakectl injected a scheduled event and confirmed its empty turn\n'

CODEX_THREAD_ID=smoke-author threadctl --timeout 5 --json notify "$inspect_thread" \
  "Advisory smoke notice." >"$SMOKE_ROOT/notify.json"
"$PYTHON" - "$SMOKE_ROOT/notify.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["threadId"] == sys.argv[2]
assert result["author"] == "smoke-author"
assert result["outcome"] == "accepted"
assert result["itemId"].startswith("amsg_")
PY

threadctl --timeout 5 --json wake "$inspect_thread" >"$SMOKE_ROOT/wake.json"
"$PYTHON" - "$SMOKE_ROOT/wake.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["threadId"] == sys.argv[2]
assert result["outcome"] in {"confirmedStarted", "notSubmittedActive"}
assert result.get("turnId")
if result["outcome"] == "confirmedStarted":
    assert isinstance(result["observedStatus"], str)
    assert result["observedStatus"]
PY
printf 'threadctl preserved empty-wake idleness semantics after scheduled delivery\n'

threadctl --timeout 5 --json terminals "$inspect_thread" \
  >"$SMOKE_ROOT/terminals.json"
"$PYTHON" - "$SMOKE_ROOT/terminals.json" "$inspect_thread" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    result = json.load(handle)
assert result["threadId"] == sys.argv[2]
assert result["terminals"] == []
PY

if threadctl --timeout 5 terminate-terminal "$inspect_thread" 999999 \
  --item missing-item >"$SMOKE_ROOT/terminate.out" \
  2>"$SMOKE_ROOT/terminate.err"; then
  fail "expected missing terminal process to fail"
fi
grep -Fq 'background terminal not found: 999999' "$SMOKE_ROOT/terminate.err" || {
  sed -n '1,40p' "$SMOKE_ROOT/terminate.err" >&2
  fail "unexpected terminal identity error"
}

PYTHONPATH="$ROOT/packages/codex-threadctl/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" - "$inspect_thread" <<'PY'
import asyncio
import sys

from codex_threadctl.appserver import AppServer


async def main():
    async with AppServer("unix://", 5) as app:
        result = await app.request(
            "thread/backgroundTerminals/terminate",
            {"threadId": sys.argv[1], "processId": "999999"},
        )
    assert result == {"terminated": False}


asyncio.run(main())
PY
printf 'threadctl checked terminal identity and reached native termination API\n'

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

log "memoryctl compaction discovery and injection"
memoryctl --json list "$memory_thread" >"$SMOKE_ROOT/memory-list.json"
memoryctl --json export "$memory_thread@window:1" \
  --output "$SMOKE_ROOT/memory-export.json" >"$SMOKE_ROOT/memory-export-result.json"
threadctl --timeout 5 resume "$agent_thread" --continue-goal \
  >"$SMOKE_ROOT/memory-target-resume.out"
memoryctl --timeout 5 --json inject --to "$agent_thread" \
  --state "$memory_thread@window:1" --purpose "isolated app-server smoke" \
  >"$SMOKE_ROOT/memory-inject.json"
memoryctl --json list "$agent_thread" --origin standalone \
  >"$SMOKE_ROOT/memory-target.json"
"$PYTHON" - "$SMOKE_ROOT/memory-list.json" \
  "$SMOKE_ROOT/memory-export.json" "$SMOKE_ROOT/memory-inject.json" \
  "$SMOKE_ROOT/memory-target.json" "$memory_thread" "$agent_thread" <<'PY'
import json
import os
import sys

list_path, export_path, inject_path, target_path, source_id, target_id = sys.argv[1:]
with open(list_path, encoding="utf-8") as handle:
    source = json.load(handle)
with open(export_path, encoding="utf-8") as handle:
    exported = json.load(handle)
with open(inject_path, encoding="utf-8") as handle:
    injected = json.load(handle)
with open(target_path, encoding="utf-8") as handle:
    target = json.load(handle)

state = source["states"][0]
assert source["threadId"] == source_id
assert state["origin"] == "checkpoint"
assert state["windowNumber"] == 1
assert exported["scope"] == "memory"
exported_digest = exported["memory"]["id"].removeprefix("sha256:")
assert state["memoryId"] == f"m:{exported_digest[:12]}"
assert os.stat(export_path).st_mode & 0o777 == 0o600
assert injected["outcome"] == "accepted"
assert injected["targetThreadId"] == target_id
assert injected["memoryIds"] == [state["memoryId"]]
assert injected["turnBinding"] == "source"
assert injected["sourceBasis"] == "local-rollout"
assert injected["perspectiveFraming"] == "boundaries"
assert injected["purposeDelivery"] == "attributed-boundary"
assert "activeTurnId" not in injected
assert target["states"][0]["origin"] == "standalone"
assert target["states"][0]["memoryId"] == state["memoryId"]
with open(target["rolloutPath"], encoding="utf-8") as handle:
    records = [json.loads(line) for line in handle if line.strip()]
frames = [
    record["payload"]
    for record in records
    if record.get("type") == "response_item"
    and record.get("payload", {}).get("type") == "agent_message"
    and record["payload"].get("author") == "memoryctl"
]
assert len(frames) == 2
frame_events = [json.loads(frame["content"][0]["text"]) for frame in frames]
assert [event["event"] for event in frame_events] == [
    "memoryctl.perspective.open",
    "memoryctl.perspective.close",
]
assert frame_events[1]["callerPurpose"]["text"] == "isolated app-server smoke"
PY
printf 'memoryctl discovered, exported, injected, and re-observed opaque memory\n'

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
