from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys

from codex_threadctl.errors import ThreadctlError

from .errors import WakectlError
from .parser import build_parser


async def dispatch(args: argparse.Namespace) -> int:
    result = args.func(args)
    if asyncio.iscoroutine(result):
        return await result
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except BrokenPipeError:
        return 1
    except (OSError, sqlite3.Error, ThreadctlError, WakectlError) as exc:
        print(f"codex-wakectl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
