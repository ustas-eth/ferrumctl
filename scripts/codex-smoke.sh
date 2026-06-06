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
  PYTHONPATH="$ROOT/packages/codex-wakectl/src${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -c 'import sys; from codex_wakectl.cli import main; raise SystemExit(main(sys.argv[1:]))' "$@"
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

log "Codex version"
codex_version=$("$CODEX_BIN" --version)
printf '%s\n' "$codex_version"
codex_semver=$(printf '%s\n' "$codex_version" | sed -n 's/^codex-cli \([0-9][0-9.]*\)$/\1/p')

parser_tag=$(sed -n 's/.*tag = "\(rust-v[^"]*\)".*/\1/p' "$ROOT/packages/codex-readcov/Cargo.toml")
if [[ -n "$parser_tag" ]]; then
  printf 'codex-readcov parser dependency: codex-shell-command %s\n' "$parser_tag"
fi
if [[ -n "$codex_semver" && -n "$parser_tag" && "$parser_tag" != "rust-v$codex_semver" ]]; then
  fail "codex-readcov parser tag $parser_tag does not match codex-cli $codex_semver"
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

log "wakectl unix app-server compatibility"
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

wakectl --timeout 5 loaded >"$SMOKE_ROOT/loaded.out"
printf 'wakectl reached app-server; loaded threads: %s\n' "$(wc -l <"$SMOKE_ROOT/loaded.out")"

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
            "type": "function_call",
            "name": "exec_command",
            "arguments": json.dumps({
                "cmd": "cat src/a.rs && sed -n '1,5p' src/b.rs",
            }),
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
printf 'readcov parsed fixture rollout\n'

printf '\ncodex smoke passed\n'
