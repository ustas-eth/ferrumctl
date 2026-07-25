#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_FILES = {
    "Cargo.lock",
    "Cargo.toml",
    "LICENSE",
    "README.md",
    "pyproject.toml",
}
RELEASE_DIRECTORIES = {"plugins", "src"}
STABLE_VERSION = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
)


class ReleaseVersionError(RuntimeError):
    pass


def git(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def resolve_base(root: Path, explicit: str | None = None) -> str:
    requested = explicit or os.environ.get("FERRUMCTL_RELEASE_BASE")
    if requested:
        result = git(
            root,
            "rev-parse",
            "--verify",
            f"{requested}^{{commit}}",
            check=False,
        )
        if result.returncode != 0:
            raise ReleaseVersionError(f"release base is not a commit: {requested}")
        return result.stdout.strip()

    for reference in ("origin/main", "main"):
        exists = git(
            root,
            "rev-parse",
            "--verify",
            f"{reference}^{{commit}}",
            check=False,
        )
        if exists.returncode != 0:
            continue
        merged = git(root, "merge-base", "HEAD", reference, check=False)
        if merged.returncode == 0 and merged.stdout.strip():
            return merged.stdout.strip()

    raise ReleaseVersionError(
        "cannot find a release base; pass --base or set FERRUMCTL_RELEASE_BASE"
    )


def is_release_input(path: str) -> bool:
    parts = Path(path).parts
    if len(parts) < 3 or parts[0] != "packages":
        return False
    return parts[2] in RELEASE_FILES or parts[2] in RELEASE_DIRECTORIES


def changed_release_files(root: Path, base: str) -> dict[str, list[str]]:
    changed = git(
        root,
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        "--diff-filter=ACMRTUXBD",
        base,
        "--",
        "packages",
    ).stdout.split("\0")
    untracked = git(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        "packages",
    ).stdout.splitlines()

    packages: dict[str, list[str]] = {}
    for path in sorted(set(changed + untracked) - {""}):
        if not is_release_input(path):
            continue
        package = Path(path).parts[1]
        packages.setdefault(package, []).append(path)
    return packages


def parse_version(text: str, filename: str) -> str:
    document = tomllib.loads(text)
    section = "project" if filename == "pyproject.toml" else "package"
    metadata = document.get(section)
    if not isinstance(metadata, dict):
        raise ReleaseVersionError(f"{filename}: missing [{section}] table")
    version = metadata.get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseVersionError(f"{filename}: missing version")
    return version


def version_key(version: str, package: str) -> tuple[int, int, int]:
    match = STABLE_VERSION.fullmatch(version)
    if match is None:
        raise ReleaseVersionError(
            f"{package}: version must use stable MAJOR.MINOR.PATCH form: {version}"
        )
    return tuple(int(part) for part in match.groups())


def current_version(root: Path, package: str) -> str | None:
    package_root = root / "packages" / package
    for filename in ("pyproject.toml", "Cargo.toml"):
        path = package_root / filename
        if path.is_file():
            return parse_version(path.read_text(), filename)
    return None


def base_version(root: Path, base: str, package: str) -> str | None:
    for filename in ("pyproject.toml", "Cargo.toml"):
        relative = f"packages/{package}/{filename}"
        result = git(root, "show", f"{base}:{relative}", check=False)
        if result.returncode == 0:
            return parse_version(result.stdout, filename)
    return None


def version_report(
    root: Path,
    base: str,
) -> tuple[list[tuple[str, str | None, str]], list[str]]:
    changes: list[tuple[str, str | None, str]] = []
    errors: list[str] = []
    for package, paths in changed_release_files(root, base).items():
        current = current_version(root, package)
        if current is None:
            continue
        previous = base_version(root, base, package)
        changes.append((package, previous, current))
        if previous is None:
            continue
        current_key = version_key(current, package)
        previous_key = version_key(previous, package)
        if current_key <= previous_key:
            sample = ", ".join(paths[:3])
            if len(paths) > 3:
                sample += f", and {len(paths) - 3} more"
            if current_key == previous_key:
                errors.append(
                    f"{package}: release inputs changed but version remains "
                    f"{current} ({sample})"
                )
            else:
                errors.append(
                    f"{package}: release inputs changed but version did not increase "
                    f"from {previous} to {current} ({sample})"
                )
    return changes, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Require fresh package versions for changed release artifacts"
    )
    parser.add_argument(
        "--base",
        help=(
            "Git revision to compare with "
            "(default: merge base with origin/main or main)"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        base = resolve_base(ROOT, args.base)
        changes, errors = version_report(ROOT, base)
    except (
        OSError,
        subprocess.SubprocessError,
        tomllib.TOMLDecodeError,
        ReleaseVersionError,
    ) as exc:
        print(f"check-release-versions: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"check-release-versions: {error}", file=sys.stderr)
        return 1

    short_base = base[:12]
    for package, previous, current in changes:
        if previous is None:
            print(f"{package}: new at {current}")
        else:
            print(f"{package}: {previous} -> {current}")
    print(
        f"validated {len(changes)} changed package(s) "
        f"against {short_base}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
