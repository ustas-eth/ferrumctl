from __future__ import annotations

import argparse
import json
import os
import sys

from .agents import (
    enrich_thread,
    list_agent_tree,
    resolve_agent_path,
    resolve_thread_reference,
)
from .appserver import (
    AppServer,
    create_thread,
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
    format_agents,
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
    "agentPath",
    "agentDepth",
    "canAcceptDirectInput",
    "inputOwner",
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


async def cmd_create(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        created = await create_thread(
            app,
            args.cwd,
            model=args.model,
            model_provider=args.model_provider,
        )
    if args.json:
        thread = created["thread"]
        print(
            json.dumps(
                {
                    "threadId": created["threadId"],
                    "cwd": thread.get("cwd", args.cwd),
                    "model": thread.get("model", args.model),
                    "modelProvider": thread.get(
                        "modelProvider", args.model_provider
                    ),
                    "status": thread.get("status"),
                    "instructionSources": created["instructionSources"],
                    "initializationItemId": created["initializationItemId"],
                },
                indent=2,
            )
        )
    else:
        print(created["threadId"])
    return 0


async def cmd_agents(args: argparse.Namespace) -> int:
    reference = current_identity(args.thread_id, "THREAD_ID")
    async with AppServer(args.endpoint, args.timeout) as app:
        thread_id = await resolve_thread_reference(
            app,
            reference,
            tree_thread_id=args.tree,
        )
        agents = await list_agent_tree(app, thread_id)
    if args.json:
        print(
            json.dumps(
                {
                    "rootThreadId": agents[0]["threadId"] if agents else None,
                    "agents": agents,
                },
                indent=2,
            )
        )
    else:
        output = format_agents(agents)
        if output:
            print(output)
    return 0


async def cmd_resolve(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        agent = await resolve_agent_path(
            app,
            args.agent_path,
            tree_thread_id=args.tree,
        )
    if args.json:
        print(json.dumps(agent, indent=2))
    else:
        print(agent["threadId"])
    return 0


async def cmd_list(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        parent = (
            await resolve_thread_reference(
                app,
                args.parent,
                tree_thread_id=args.tree,
            )
            if args.parent is not None
            else None
        )
        ancestor = (
            await resolve_thread_reference(
                app,
                args.ancestor,
                tree_thread_id=args.tree,
            )
            if args.ancestor is not None
            else None
        )
        threads = await list_threads(
            app,
            parent_thread_id=parent,
            ancestor_thread_id=ancestor,
            limit=args.limit,
            sort_key=THREAD_SORT_KEYS[args.sort],
        )
    records = [
        {field: enriched.get(field) for field in THREAD_LIST_FIELDS}
        for thread in threads
        for enriched in [enrich_thread(thread)]
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
        thread = enrich_thread(match["thread"])
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        thread = enrich_thread(await read_thread(app, thread_id))
        loaded = thread_id in await list_loaded(app)
    result = {
        "threadId": thread_id,
        "loaded": loaded,
        "status": thread.get("status", {"type": "unknown"}),
        "agentPath": thread.get("agentPath"),
        "agentDepth": thread.get("agentDepth"),
        "parentThreadId": thread.get("parentThreadId"),
        "canAcceptDirectInput": thread.get("canAcceptDirectInput"),
        "inputOwner": thread.get("inputOwner"),
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
                    thread_id,
                ]
                + (
                    [f"task-name={result['agentPath']}"]
                    if result["agentPath"] is not None
                    else []
                )
                + (
                    [f"direct-input={str(result['canAcceptDirectInput']).lower()}"]
                    if result["canAcceptDirectInput"] is not None
                    else []
                )
                + [f"input={result['inputOwner']}"]
            )
        )
    return 0


async def cmd_inspect(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        local_rollout = app.endpoint.startswith("unix://")
        turn_limit = 1 if args.no_previous else 2
        history_backend = "thread/turns/list"
        history_error = None
        recent_items: list[dict[str, object]] = []
        try:
            turns = (
                await list_turn_page(
                    app,
                    thread_id,
                    limit=turn_limit,
                    items_view="summary" if args.brief else "full",
                )
            ).get("data", [])
        except AppServerResponseError as exc:
            if not unsupported_method(exc):
                raise
            turns, recent_items = await native_inspection_history(
                app,
                thread_id,
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
            goal = await get_goal(app, thread_id)
        except ThreadctlError as exc:
            goal_error = str(exc)
        thread = enrich_thread(await read_thread(app, thread_id))
        loaded = thread_id in await list_loaded(app)

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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        messages, backend = await recent_messages(
            app,
            thread_id,
            turn_id=args.turn,
            after=tuple(args.after) if args.after else None,
            before=tuple(args.before) if args.before else None,
            limit=args.limit,
        )
    if args.json:
        print(
            json.dumps(
                {
                    "threadId": thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        selection = await select_materialized_items(
            app,
            thread_id,
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
                    "threadId": thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        message = await find_message(
            app,
            thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        result = await start_turn(app, thread_id, args.message)
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        result = await notify_thread(
            app,
            thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        result = await wake_thread(app, thread_id)
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        result = await steer_turn(
            app,
            thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        result = await interrupt_thread(
            app,
            thread_id,
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        terminals = await list_background_terminals(
            app,
            thread_id,
            limit=args.limit,
        )
    records = [
        {field: terminal.get(field) for field in TERMINAL_FIELDS}
        for terminal in terminals
    ]
    if args.json:
        print(
            json.dumps(
                {"threadId": thread_id, "terminals": records},
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
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        terminated = await terminate_background_terminal(
            app,
            thread_id,
            args.process_id,
            args.item_id,
        )
    if not terminated:
        raise ThreadctlError(
            f"background terminal was not terminated: {args.process_id}"
        )
    result = {
        "threadId": thread_id,
        "processId": args.process_id,
        "itemId": args.item_id,
        "terminated": True,
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"terminated\t{thread_id}\t{args.process_id}"
            f"\titem={args.item_id}"
        )
    return 0


async def cmd_resume(args: argparse.Namespace) -> int:
    async with AppServer(args.endpoint, args.timeout) as app:
        thread_id = await resolve_thread_reference(
            app,
            args.thread_id,
            tree_thread_id=args.tree,
        )
        thread = await resume_thread(
            app,
            thread_id,
            continue_goal=args.continue_goal,
        )
    result = {
        "threadId": thread.get("id", thread_id),
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
