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
run cmp LICENSE packages/codex-threadctl/LICENSE
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
  cd packages/codex-threadctl
  run env PYTHONPATH=src "$PYTHON" -m unittest discover -s tests -v
)

(
  cd packages/codex-readcov
  run "$CARGO" test --locked
)

(
  package_root=$(mktemp -d "${TMPDIR:-/tmp}/ferrumctl-package-check.XXXXXX")
  trap 'rm -rf -- "$package_root"' EXIT
  tool_dir="$package_root/tools"
  bin_dir="$package_root/bin"
  export UV_TOOL_DIR="$tool_dir"
  export UV_TOOL_BIN_DIR="$bin_dir"
  export UV_CACHE_DIR="$package_root/cache"
  export UV_LINK_MODE=copy
  export PATH="$bin_dir:$PATH"

  run "$UV" tool install ./packages/codex-goalctl
  run "$UV" tool install ./packages/codex-wakectl
  run "$UV" tool install ./packages/codex-threadctl
  run "$bin_dir/codex-goalctl" --version
  run "$bin_dir/codex-wakectl" --version
  run "$bin_dir/codex-threadctl" --version
)

run packages/codex-readcov/target/debug/codex-readcov --version

printf '\nchecks passed\n'
