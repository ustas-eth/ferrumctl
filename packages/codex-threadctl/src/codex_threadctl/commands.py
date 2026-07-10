from __future__ import annotations

import argparse
import json
import sys

from .appserver import (
    AppServer,
    compact_thread,
    get_goal,
    interrupt_thread,
    list_loaded,
    list_turn_page,
    read_thread,
)
from .context import read_context_state
from .errors import ThreadctlError
from .formatting import format_inspection, format_messages
from .turns import build_inspection, find_message, recent_messages


async def cmd_loaded(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread_ids = await list_loaded(app)
    if args.json:
        print(json.dumps({"threadIds": thread_ids}, indent=2))
    else:
        print("\n".join(thread_ids))
    return 0


async def cmd_status(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread = await read_thread(app, args.thread_id)
        loaded = args.thread_id in await list_loaded(app)
    result = {
        "threadId": args.thread_id,
        "loaded": loaded,
        "status": thread.get("status", {"type": "unknown"}),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        loaded_label = "loaded" if loaded else "not-loaded"
        print(
            "\t".join(
                [
                    loaded_label,
                    str(result["status"].get("type", "unknown")),
                    args.thread_id,
                ]
            )
        )
    return 0


async def cmd_inspect(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        detailed = []
        if not args.brief:
            detailed = (
                await list_turn_page(
                    app,
                    args.thread_id,
                    limit=1,
                    items_view="full",
                )
            ).get("data", [])
        summary_turns = (
            await list_turn_page(
                app,
                args.thread_id,
                limit=1 if args.no_previous else 2,
                items_view="summary",
            )
        ).get("data", [])
        goal = None
        goal_error = None
        try:
            goal = await get_goal(app, args.thread_id)
        except ThreadctlError as exc:
            goal_error = str(exc)
        thread = await read_thread(app, args.thread_id)
        loaded = args.thread_id in await list_loaded(app)

    context, compaction = read_context_state(thread.get("path"))
    inspection = build_inspection(
        thread,
        loaded=loaded,
        goal=goal,
        goal_error=goal_error,
        detailed_turn=detailed[0] if detailed else None,
        summary_turns=summary_turns,
        item_limit=args.items,
        context=context,
        compaction=compaction,
    )
    if args.json:
        print(json.dumps(inspection, indent=2))
    else:
        print(format_inspection(inspection))
    return 0


async def cmd_messages(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        messages = await recent_messages(app, args.thread_id, limit=args.limit)
    if args.json:
        print(json.dumps({"threadId": args.thread_id, "messages": messages}, indent=2))
    else:
        output = format_messages(messages)
        if output:
            print(output)
    return 0


async def cmd_message(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        message = await find_message(
            app,
            args.thread_id,
            args.turn_id,
            args.item_id,
        )
    if args.json:
        print(json.dumps(message, indent=2))
    else:
        text = message["text"]
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    return 0


async def cmd_interrupt(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await interrupt_thread(app, args.thread_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['status']}\t{result['turnId']}")
    return 0


async def cmd_compact(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await compact_thread(app, args.thread_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['status']}\t{result['threadId']}")
    return 0
