from __future__ import annotations

import argparse
import asyncio
import sys

import websockets

from .errors import ThreadctlError
from .parser import build_parser


async def dispatch(args: argparse.Namespace) -> int:
    return await args.func(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except BrokenPipeError:
        return 1
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        print(f"codex-threadctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
