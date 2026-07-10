from __future__ import annotations

import argparse
import json

from .appserver import AppServer, send_turn


async def cmd_send(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        turn = await send_turn(
            app,
            args.thread_id,
            args.message,
            allow_active=args.allow_active,
        )
    if args.json:
        print(json.dumps({"turn": turn}, indent=2))
    else:
        print(turn.get("id", "sent"))
    return 0
