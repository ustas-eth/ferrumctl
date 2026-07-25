from __future__ import annotations

import argparse
import json
import os
import sys

from .appserver import (
    AppServer,
    get_goal,
    interrupt_thread,
    list_background_terminals,
    list_loaded,
    list_threads,
    list_turn_page,
    notify_thread,
    read_thread,
    resume_thread,
    search_threads,
    start_turn,
    steer_turn,
    terminate_background_terminal,
    unsupported_method,
    wake_thread,
)
from .context import read_context_state
from .errors import AppServerResponseError, ThreadctlError
from .formatting import (
    format_inspection,
    format_items,
    format_messages,
    format_terminals,
    format_thread_list,
)
from .history import (
    native_inspection_history,
    select_materialized_items,
)
from .items import item_record
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

THREAD_SEARCH_FIELDS = tuple(field for field in THREAD_LIST_FIELDS if field != "preview")

TERMINAL_FIELDS = (
    "processId",
    "itemId",
    "osPid",
    "cpuPercent",
    "rssKb",
    "cwd",
    "command",
)


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


async def cmd_search(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        matches = await search_threads(
            app,
            args.search_term,
            limit=args.limit,
            sort_key=THREAD_SORT_KEYS[args.sort],
        )
    records = []
    for match in matches:
        thread = match["thread"]
        record = {field: thread.get(field) for field in THREAD_SEARCH_FIELDS}
        record["snippet"] = match["snippet"]
        records.append(record)
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
        turn_limit = 1 if args.no_previous else 2
        history_backend = "thread/turns/list"
        history_error = None
        recent_items: list[dict[str, object]] = []
        try:
            turns = (
                await list_turn_page(
                    app,
                    args.thread_id,
                    limit=turn_limit,
                    items_view="summary" if args.brief else "full",
                )
            ).get("data", [])
        except AppServerResponseError as exc:
            if not unsupported_method(exc):
                raise
            turns, recent_items = await native_inspection_history(
                app,
                args.thread_id,
                turn_limit=turn_limit,
                item_limit=args.items,
                brief=args.brief,
            )
            history_backend = "thread/items/list"
            if recent_items:
                history_error = (
                    "this Codex version does not expose turn ids for paginated "
                    "history; showing recent items without turn metadata"
                )
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
        turns=turns,
        item_limit=args.items,
        context=context,
        compaction=compaction,
        context_error=context_error,
        history_backend=history_backend,
        history_error=history_error,
        recent_items=recent_items,
    )
    if args.json:
        print(json.dumps(inspection, indent=2))
    else:
        print(format_inspection(inspection))
    return 0


async def cmd_messages(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        messages, backend = await recent_messages(
            app,
            args.thread_id,
            turn_id=args.turn,
            after=tuple(args.after) if args.after else None,
            before=tuple(args.before) if args.before else None,
            limit=args.limit,
        )
    if args.json:
        print(
            json.dumps(
                {
                    "threadId": args.thread_id,
                    "view": "materialized",
                    "backend": backend,
                    "messages": messages,
                },
                indent=2,
            )
        )
    else:
        output = format_messages(messages)
        if output:
            print(output)
    return 0


async def cmd_items(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        selection = await select_materialized_items(
            app,
            args.thread_id,
            turn_id=args.turn,
            after=tuple(args.after) if args.after else None,
            before=tuple(args.before) if args.before else None,
            types=set(args.types),
            limit=args.limit,
        )
    records = [item_record(entry.turn, entry.item) for entry in selection.entries]
    if args.json:
        print(
            json.dumps(
                {
                    "threadId": args.thread_id,
                    "view": "materialized",
                    "backend": selection.backend,
                    "items": records,
                },
                indent=2,
            )
        )
    else:
        output = format_items(records)
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


def current_identity(value: str | None, option: str) -> str:
    identity = value or os.environ.get("CODEX_THREAD_ID")
    if identity is None or not identity.strip():
        raise ThreadctlError(
            f"{option} is required when CODEX_THREAD_ID is not set"
        )
    return identity


async def cmd_notify(args: argparse.Namespace) -> int:
    author = current_identity(args.author, "--from")
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await notify_thread(
            app,
            args.thread_id,
            author,
            args.message,
        )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['outcome']}\t{result['threadId']}")
    return 0


async def cmd_wake(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        result = await wake_thread(app, args.thread_id)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        fields = [result["outcome"], result["threadId"]]
        if "turnId" in result:
            fields.append(f"turn={result['turnId']}")
        if "observedStatus" in result:
            fields.append(f"observed={result['observedStatus']}")
        if "reason" in result:
            fields.append(
                f"reason={json.dumps(result['reason'], ensure_ascii=False)}"
            )
        print("\t".join(fields))
    return 0 if result["outcome"] in {"confirmedStarted", "notSubmittedActive"} else 1


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


async def cmd_terminals(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        terminals = await list_background_terminals(
            app,
            args.thread_id,
            limit=args.limit,
        )
    records = [
        {field: terminal.get(field) for field in TERMINAL_FIELDS}
        for terminal in terminals
    ]
    if args.json:
        print(
            json.dumps(
                {"threadId": args.thread_id, "terminals": records},
                indent=2,
            )
        )
    else:
        output = format_terminals(records)
        if output:
            print(output)
    return 0


async def cmd_terminate_terminal(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        terminated = await terminate_background_terminal(
            app,
            args.thread_id,
            args.process_id,
            args.item_id,
        )
    if not terminated:
        raise ThreadctlError(
            f"background terminal was not terminated: {args.process_id}"
        )
    result = {
        "threadId": args.thread_id,
        "processId": args.process_id,
        "itemId": args.item_id,
        "terminated": True,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"terminated\t{args.thread_id}\t{args.process_id}"
            f"\titem={args.item_id}"
        )
    return 0


async def cmd_resume(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread = await resume_thread(
            app,
            args.thread_id,
            continue_goal=args.continue_goal,
        )
    result = {
        "threadId": thread.get("id", args.thread_id),
        "status": thread.get("status", {"type": "unknown"}),
        "goalContinuationAllowed": args.continue_goal,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = result["status"]
        name = status.get("type", "unknown") if isinstance(status, dict) else "unknown"
        fields = [name, str(result["threadId"])]
        if args.continue_goal:
            fields.append("goal-continuation=allowed")
        print("\t".join(fields))
    return 0
