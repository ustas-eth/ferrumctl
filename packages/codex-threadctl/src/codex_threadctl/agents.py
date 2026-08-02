from __future__ import annotations

import os
from typing import Any

from .appserver import AppServer, list_loaded, list_threads, read_thread
from .errors import ThreadctlError


AGENT_PATH_ROOT = "/root"


def is_agent_path(value: str) -> bool:
    return value == AGENT_PATH_ROOT or value.startswith(f"{AGENT_PATH_ROOT}/")


def validate_agent_path(value: str) -> str:
    segments = value.split("/")[2:] if is_agent_path(value) else []
    if not is_agent_path(value) or any(
        segment == "root"
        or not segment
        or not all(
            char.isascii() and (char.islower() or char.isdigit() or char == "_")
            for char in segment
        )
        for segment in segments
    ):
        raise ThreadctlError(
            "agent path must be /root or use lowercase letters, digits, and "
            "underscores in each non-root segment"
        )
    return value


def spawn_metadata(thread: dict[str, Any]) -> dict[str, Any] | None:
    source = thread.get("source")
    if not isinstance(source, dict):
        return None
    subagent = source.get("subAgent")
    if subagent is None:
        subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return None
    spawned = subagent.get("thread_spawn")
    return spawned if isinstance(spawned, dict) else None


def agent_path(thread: dict[str, Any]) -> str | None:
    spawned = spawn_metadata(thread)
    value = spawned.get("agent_path") if spawned is not None else None
    return value if isinstance(value, str) and is_agent_path(value) else None


def parent_thread_id(thread: dict[str, Any]) -> str | None:
    parent = thread.get("parentThreadId")
    if isinstance(parent, str) and parent:
        return parent
    spawned = spawn_metadata(thread)
    parent = spawned.get("parent_thread_id") if spawned is not None else None
    return parent if isinstance(parent, str) and parent else None


def agent_depth(thread: dict[str, Any]) -> int | None:
    spawned = spawn_metadata(thread)
    depth = spawned.get("depth") if spawned is not None else None
    return depth if isinstance(depth, int) and depth >= 0 else None


def enrich_thread(thread: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(thread)
    enriched["parentThreadId"] = parent_thread_id(thread)
    enriched["agentPath"] = agent_path(thread)
    enriched["agentDepth"] = agent_depth(thread)
    enriched["inputOwner"] = direct_input_owner(thread)
    return enriched


def direct_input_owner(thread: dict[str, Any]) -> str:
    accepted = thread.get("canAcceptDirectInput")
    if accepted is True:
        return "direct"
    if accepted is False or agent_path(thread) is not None:
        return "parent"
    return "unknown"


def agent_record(
    thread: dict[str, Any],
    *,
    root: bool,
    loaded_thread_ids: set[str],
) -> dict[str, Any]:
    thread = enrich_thread(thread)
    thread_id = thread.get("id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ThreadctlError("app-server returned an agent without a thread id")
    status = thread.get("status")
    if not isinstance(status, dict):
        status = {"type": "unknown"}
    path = AGENT_PATH_ROOT if root else thread.get("agentPath")
    depth = 0 if root else thread.get("agentDepth")
    return {
        "threadId": thread_id,
        "agentPath": path,
        "parentThreadId": None if root else thread.get("parentThreadId"),
        "depth": depth,
        "loaded": thread_id in loaded_thread_ids,
        "status": status,
        "canAcceptDirectInput": thread.get("canAcceptDirectInput"),
        "inputOwner": direct_input_owner(thread),
        "nickname": thread.get("agentNickname"),
        "role": thread.get("agentRole"),
    }


async def read_agent_lineage(
    app: AppServer,
    thread_id: str,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    current_id = thread_id
    lineage: list[dict[str, Any]] = []
    while True:
        if current_id in seen:
            raise ThreadctlError("thread parent relationship contains a cycle")
        seen.add(current_id)
        thread = enrich_thread(await read_thread(app, current_id))
        actual_id = thread.get("id")
        if not isinstance(actual_id, str) or not actual_id:
            raise ThreadctlError("app-server returned a thread without an id")
        lineage.append(thread)
        parent = thread.get("parentThreadId")
        if parent is None:
            return lineage
        current_id = parent


async def list_agent_tree(app: AppServer, thread_id: str) -> list[dict[str, Any]]:
    lineage = await read_agent_lineage(app, thread_id)
    root = lineage[-1]
    root_id = root["id"]
    descendants = await list_threads(
        app,
        ancestor_thread_id=root_id,
        limit=0,
        sort_key="created_at",
    )
    loaded = set(await list_loaded(app))
    threads_by_id = {
        thread["id"]: thread
        for thread in [root, *descendants, *lineage[:-1]]
    }
    records = [
        agent_record(
            thread,
            root=record_id == root_id,
            loaded_thread_ids=loaded,
        )
        for record_id, thread in threads_by_id.items()
    ]
    return sorted(
        records,
        key=lambda record: (
            record["depth"] if isinstance(record["depth"], int) else 1 << 30,
            record["agentPath"] or "",
            record["threadId"],
        ),
    )


def matching_records(
    records: list[dict[str, Any]], agent_path_value: str
) -> list[dict[str, Any]]:
    return [
        record for record in records if record.get("agentPath") == agent_path_value
    ]


def one_match(agent_path_value: str, matches: list[dict[str, Any]]) -> dict[str, Any]:
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ThreadctlError(f"agent path not found: {agent_path_value}")
    ids = ", ".join(str(match["threadId"]) for match in matches)
    raise ThreadctlError(
        f"agent path is ambiguous: {agent_path_value}; matching threads: {ids}"
    )


async def loaded_agent_records(app: AppServer) -> list[dict[str, Any]]:
    loaded = set(await list_loaded(app))
    records = []
    for thread_id in sorted(loaded):
        thread = enrich_thread(await read_thread(app, thread_id))
        records.append(
            agent_record(
                thread,
                root=thread.get("parentThreadId") is None,
                loaded_thread_ids=loaded,
            )
        )
    return records


async def resolve_agent_path(
    app: AppServer,
    path: str,
    *,
    tree_thread_id: str | None = None,
) -> dict[str, Any]:
    path = validate_agent_path(path)
    anchor = tree_thread_id or os.environ.get("CODEX_THREAD_ID")
    if anchor is not None and anchor.strip():
        if is_agent_path(anchor):
            raise ThreadctlError("--tree and CODEX_THREAD_ID must identify a thread by id")
        records = await list_agent_tree(app, anchor)
    else:
        records = await loaded_agent_records(app)
    return one_match(path, matching_records(records, path))


async def resolve_thread_reference(
    app: AppServer,
    reference: str,
    *,
    tree_thread_id: str | None = None,
) -> str:
    if not is_agent_path(reference):
        return reference
    record = await resolve_agent_path(
        app,
        reference,
        tree_thread_id=tree_thread_id,
    )
    return str(record["threadId"])
