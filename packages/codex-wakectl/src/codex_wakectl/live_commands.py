from __future__ import annotations

import argparse
import json

from .activity import build_inspection, format_inspection
from .appserver import (
    AppServer,
    get_goal,
    get_thread_status,
    interrupt_turn,
    list_loaded,
    list_thread_turns,
    read_thread,
    send_turn,
    status_name,
)
from .errors import WakectlError


async def cmd_loaded(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        ids = await list_loaded(app)
    if args.json:
        print(json.dumps({"threads": ids}, indent=2))
    else:
        for thread_id in ids:
            print(thread_id)
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        loaded = await list_loaded(app)
        status = await get_thread_status(app, args.thread_id)
    result = {
        "threadId": args.thread_id,
        "loaded": args.thread_id in loaded,
        "status": status,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        loaded_label = "loaded" if result["loaded"] else "not-loaded"
        print(f"{loaded_label}\t{status_name(status)}\t{args.thread_id}")
    return 0


async def cmd_inspect(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        loaded = args.thread_id in await list_loaded(app)
        thread = await read_thread(app, args.thread_id)
        goal_error = None
        try:
            goal = await get_goal(app, args.thread_id)
        except WakectlError as exc:
            goal = None
            goal_error = str(exc)
        summary_turns = await list_thread_turns(
            app,
            args.thread_id,
            limit=2,
            items_view="summary",
        )
        detailed = await list_thread_turns(
            app,
            args.thread_id,
            limit=1,
            items_view="full",
        )
    inspection = build_inspection(
        thread,
        loaded=loaded,
        goal=goal,
        goal_error=goal_error,
        detailed_turn=detailed[0] if detailed else None,
        summary_turns=summary_turns,
        item_limit=args.items,
    )
    if args.json:
        print(json.dumps(inspection, indent=2))
    else:
        print(format_inspection(inspection))
    return 0


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


async def cmd_interrupt(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        turn = await interrupt_turn(app, args.thread_id)
    result = {
        "threadId": args.thread_id,
        "turnId": turn.get("id"),
        "status": turn.get("status", "interrupted"),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['status']}\t{result['turnId'] or '-'}")
    return 0
