#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${PYTHON:-python3}
CARGO=${CARGO:-cargo}

cd "$ROOT"

run() {
  printf '\n==> %s\n' "$*"
  "$@"
}

run "$PYTHON" scripts/sync-skill-references.py --check
printf '\n==> %s\n' "$PYTHON -m json.tool scripts/skill-references.json"
"$PYTHON" -m json.tool scripts/skill-references.json >/dev/null
run bash -n scripts/check.sh
run bash -n scripts/codex-smoke.sh
run test -x scripts/check.sh
run test -x scripts/codex-smoke.sh
run git diff --check

(
  cd packages/codex-goalctl
  run env PYTHONPATH=src "$PYTHON" -m unittest discover -s tests -v
)

(
  cd packages/codex-wakectl
  run env PYTHONPATH=src "$PYTHON" -m unittest discover -s tests -v
)

(
  cd packages/codex-readcov
  run "$CARGO" test --locked
)

printf '\nchecks passed\n'
