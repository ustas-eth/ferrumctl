from __future__ import annotations

import argparse
import json
import sys

from .appserver import (
    AppServer,
    get_goal,
    interrupt_thread,
    list_loaded,
    list_threads,
    list_turn_page,
    read_thread,
    resume_thread,
    start_turn,
    steer_turn,
)
from .context import read_context_state
from .errors import ThreadctlError
from .formatting import format_inspection, format_messages, format_thread_list
from .turns import build_inspection, find_message, recent_messages


THREAD_LIST_FIELDS = (
    "id",
    "status",
    "createdAt",
    "updatedAt",
    "recencyAt",
    "name",
    "agentNickname",
    "agentRole",
    "parentThreadId",
    "forkedFromId",
    "cwd",
    "modelProvider",
    "cliVersion",
    "source",
    "preview",
)

THREAD_SORT_KEYS = {
    "created": "created_at",
    "recency": "recency_at",
    "updated": "updated_at",
}


async def cmd_loaded(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread_ids = await list_loaded(app)
    if args.json:
        print(json.dumps({"threadIds": thread_ids}, indent=2))
    elif thread_ids:
        print("\n".join(thread_ids))
    return 0


async def cmd_list(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        threads = await list_threads(
            app,
            parent_thread_id=args.parent,
            ancestor_thread_id=args.ancestor,
            limit=args.limit,
            sort_key=THREAD_SORT_KEYS[args.sort],
        )
    records = [
        {field: thread.get(field) for field in THREAD_LIST_FIELDS}
        for thread in threads
    ]
    if args.json:
        print(json.dumps({"threads": records}, indent=2))
    else:
        output = format_thread_list(records)
        if output:
            print(output)
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
        local_rollout = app.endpoint.startswith("unix://")
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

    if local_rollout:
        context, compaction = read_context_state(thread.get("path"))
        context_error = None
    else:
        context, compaction = None, None
        context_error = "rollout context is unavailable through a remote endpoint"
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
        context_error=context_error,
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


async def cmd_start(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await start_turn(app, args.thread_id, args.message)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['delivery']}\t{result['turnId']}")
    return 0


async def cmd_steer(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await steer_turn(
            app,
            args.thread_id,
            args.turn_id,
            args.message,
        )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['delivery']}\t{result['turnId']}")
    return 0


async def cmd_interrupt(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await interrupt_thread(
            app,
            args.thread_id,
            args.turn_id,
            wait=args.wait,
        )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['status']}\t{result['turnId']}")
    return 0


async def cmd_resume(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread = await resume_thread(app, args.thread_id)
    result = {
        "threadId": thread.get("id", args.thread_id),
        "status": thread.get("status", {"type": "unknown"}),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = result["status"]
        name = status.get("type", "unknown") if isinstance(status, dict) else "unknown"
        print(f"{name}\t{result['threadId']}")
    return 0
