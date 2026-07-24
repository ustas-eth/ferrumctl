from __future__ import annotations

import sqlite3
import sys

from .errors import StreamctlError
from .parser import build_parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 1
    except (OSError, sqlite3.Error, StreamctlError) as exc:
        print(f"codex-streamctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
