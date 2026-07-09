#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON=${PYTHON:-python3}
CARGO=${CARGO:-cargo}
UV=${UV:-uv}

cd "$ROOT"

run() {
  printf '\n==> %s\n' "$*"
  "$@"
}

run "$PYTHON" scripts/sync-skill-references.py --check
run "$UV" run scripts/check_skills.py
printf '\n==> %s\n' "$PYTHON -m json.tool scripts/skill-references.json"
"$PYTHON" -m json.tool scripts/skill-references.json >/dev/null
run bash -n scripts/check.sh
run bash -n scripts/codex-smoke.sh
run test -x scripts/check.sh
run test -x scripts/codex-smoke.sh
run cmp LICENSE packages/codex-goalctl/LICENSE
run cmp LICENSE packages/codex-wakectl/LICENSE
run cmp LICENSE packages/codex-readcov/LICENSE
run "$CARGO" fmt --manifest-path packages/codex-readcov/Cargo.toml -- --check
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
