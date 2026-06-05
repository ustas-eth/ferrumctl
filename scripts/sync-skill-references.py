#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HEADER = (
    "<!-- Generated from {source}. Do not edit directly. "
    "Run `python3 scripts/sync-skill-references.py`. -->\n\n"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def clean_relative(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"path must be repo-relative: {path}")
    return candidate


def load_mapping(root: Path) -> list[tuple[Path, list[Path]]]:
    mapping_path = root / "scripts" / "skill-references.json"
    raw = json.loads(mapping_path.read_text())
    entries = []
    for item in raw["references"]:
        source = clean_relative(item["source"])
        targets = [clean_relative(target) for target in item["targets"]]
        entries.append((source, targets))
    return entries


def generated_text(source: str, text: str) -> str:
    body = text.rstrip() + "\n"
    return HEADER.format(source=source) + body


def sync(*, check: bool) -> int:
    root = repo_root()
    stale: list[str] = []
    for source, targets in load_mapping(root):
        source_path = root / source
        expected = generated_text(str(source), source_path.read_text())
        for target in targets:
            target_path = root / target
            if check:
                actual = target_path.read_text() if target_path.exists() else None
                if actual != expected:
                    stale.append(str(target))
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(expected)
            print(f"synced\t{target}")
    if stale:
        for target in stale:
            print(f"stale\t{target}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy canonical docs into bundled skill references.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if generated references are stale",
    )
    args = parser.parse_args()
    return sync(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
