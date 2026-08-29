#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path


TYPES = {
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
}
SCOPES = {
    "goalctl",
    "limitctl",
    "memoryctl",
    "readcov",
    "release",
    "repo",
    "streamctl",
    "threadctl",
    "wakectl",
}
GENERATED_PREFIXES = ("Merge ", 'Revert "', "fixup! ", "squash! ", "amend! ")
HEADER = re.compile(
    r"^(?P<type>[a-z]+)\((?P<scope>[a-z][a-z0-9-]*)\)(?P<breaking>!)?: "
    r"(?P<description>.+)$"
)
MAX_HEADER_LENGTH = 72
MIN_DESCRIPTION_LENGTH = 8


def validate_message(message: str) -> list[str]:
    lines = message.splitlines()
    header = lines[0] if lines else ""
    if any(header.startswith(prefix) for prefix in GENERATED_PREFIXES):
        return []

    match = HEADER.fullmatch(header)
    if match is None:
        return ["header must use: type(scope): concise description"]

    errors: list[str] = []
    commit_type = match.group("type")
    scope = match.group("scope")
    description = match.group("description")

    if commit_type not in TYPES:
        errors.append(f"unknown type: {commit_type}")
    if scope not in SCOPES:
        errors.append(f"unknown scope: {scope}")
    if len(header) > MAX_HEADER_LENGTH:
        errors.append(f"header exceeds {MAX_HEADER_LENGTH} characters")
    if description != description.strip():
        errors.append("description must not have leading or trailing whitespace")
    if len(description) < MIN_DESCRIPTION_LENGTH:
        errors.append(
            f"description must contain at least {MIN_DESCRIPTION_LENGTH} characters"
        )
    if description.endswith("."):
        errors.append("description must not end with a period")
    return errors


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_commit_message.py COMMIT_MSG_FILE", file=sys.stderr)
        return 2

    path = Path(args[0])
    try:
        message = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"check-commit-message: {exc}", file=sys.stderr)
        return 2

    errors = validate_message(message)
    if not errors:
        return 0

    for error in errors:
        print(f"check-commit-message: {error}", file=sys.stderr)
    print(
        "example: fix(threadctl): avoid inventing turn attribution",
        file=sys.stderr,
    )
    print(f"types: {', '.join(sorted(TYPES))}", file=sys.stderr)
    print(f"scopes: {', '.join(sorted(SCOPES))}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
