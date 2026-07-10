from __future__ import annotations

import json
from typing import Any

from .appserver import status_name
from .parsing import format_time, now_seconds


def summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    kind = item.get("type", "unknown")
    summary: dict[str, Any] = {"type": kind}
    for key in ("id", "status", "durationMs"):
        if item.get(key) is not None:
            summary[key] = item[key]

    if kind == "userMessage":
        text = "\n".join(
            entry.get("text", "")
            for entry in item.get("content", [])
            if entry.get("type") == "text"
        )
        summary["text"] = text
    elif kind == "agentMessage":
        summary["text"] = item.get("text", "")
        if item.get("phase") is not None:
            summary["phase"] = item["phase"]
    elif kind == "hookPrompt":
        summary["text"] = "\n".join(
            fragment.get("text", "") for fragment in item.get("fragments", [])
        )
    elif kind == "reasoning":
        summary["summary"] = item.get("summary", [])
    elif kind == "plan":
        summary["text"] = item.get("text", "")
    elif kind == "commandExecution":
        summary.update(
            {
                "command": item.get("command", ""),
                "cwd": item.get("cwd"),
                "exitCode": item.get("exitCode"),
            }
        )
    elif kind == "fileChange":
        summary["changes"] = [
            {"path": change.get("path"), "kind": change.get("kind")}
            for change in item.get("changes", [])
        ]
    elif kind == "mcpToolCall":
        summary.update(
            {
                "server": item.get("server"),
                "tool": item.get("tool"),
                "error": item.get("error"),
            }
        )
    elif kind == "dynamicToolCall":
        summary.update(
            {
                "namespace": item.get("namespace"),
                "tool": item.get("tool"),
                "success": item.get("success"),
            }
        )
    elif kind == "collabAgentToolCall":
        summary.update(
            {
                "tool": item.get("tool"),
                "senderThreadId": item.get("senderThreadId"),
                "receiverThreadIds": item.get("receiverThreadIds", []),
                "agentsStates": bounded_collab_states(item.get("agentsStates", {})),
            }
        )
    elif kind == "subAgentActivity":
        summary.update(
            {
                "kind": item.get("kind"),
                "agentThreadId": item.get("agentThreadId"),
                "agentPath": item.get("agentPath"),
            }
        )
    elif kind == "webSearch":
        summary.update({"query": item.get("query"), "action": item.get("action")})
    elif kind in {"imageView", "imageGeneration"}:
        summary["path"] = item.get("path") or item.get("savedPath")
    elif kind == "sleep":
        summary["durationMs"] = item.get("durationMs")
    elif kind in {"enteredReviewMode", "exitedReviewMode"}:
        summary["review"] = item.get("review")
    return summary


def summarize_turn(turn: dict[str, Any], item_limit: int) -> dict[str, Any]:
    items = turn.get("items", [])
    if item_limit > 0:
        items = items[-item_limit:]
    started_at = turn.get("startedAt")
    completed_at = turn.get("completedAt")
    now = now_seconds()
    return {
        "id": turn.get("id"),
        "status": turn.get("status"),
        "itemsView": turn.get("itemsView"),
        "error": turn.get("error"),
        "startedAt": started_at,
        "completedAt": completed_at,
        "durationMs": turn.get("durationMs"),
        "startedAgoSeconds": max(0, now - started_at) if started_at is not None else None,
        "completedAgoSeconds": (
            max(0, now - completed_at) if completed_at is not None else None
        ),
        "items": [summarize_item(item) for item in items],
    }


def merge_turn_detail(
    detailed: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(detailed)
    for key in ("status", "error", "startedAt", "completedAt", "durationMs"):
        if key in summary:
            merged[key] = summary[key]

    items = list(detailed.get("items", []))
    positions = {
        item["id"]: index
        for index, item in enumerate(items)
        if item.get("id") is not None
    }
    for item in summary.get("items", []):
        item_id = item.get("id")
        if item_id in positions:
            items[positions[item_id]] = item
        else:
            items.append(item)
            if item_id is not None:
                positions[item_id] = len(items) - 1
    merged["items"] = items
    return merged


def turn_lifecycle_changed(
    detailed: dict[str, Any], summary: dict[str, Any]
) -> bool:
    return any(
        detailed.get(key) != summary.get(key)
        for key in ("status", "error", "startedAt", "completedAt", "durationMs")
    )


def build_inspection(
    thread: dict[str, Any],
    *,
    loaded: bool,
    goal: dict[str, Any] | None,
    goal_error: str | None,
    detailed_turn: dict[str, Any] | None,
    summary_turns: list[dict[str, Any]],
    item_limit: int,
) -> dict[str, Any]:
    summary_latest = summary_turns[0] if summary_turns else None
    if (
        detailed_turn is not None
        and summary_latest is not None
        and detailed_turn.get("id") == summary_latest.get("id")
        and not turn_lifecycle_changed(detailed_turn, summary_latest)
    ):
        latest = merge_turn_detail(detailed_turn, summary_latest)
    else:
        latest = summary_latest
    previous = next(
        (
            turn
            for turn in summary_turns
            if latest is None or turn.get("id") != latest.get("id")
        ),
        None,
    )
    status = thread.get("status", {"type": "unknown"})
    return {
        "thread": {
            "id": thread.get("id"),
            "loaded": loaded,
            "status": status,
            "cwd": thread.get("cwd"),
            "name": thread.get("name"),
            "agentNickname": thread.get("agentNickname"),
            "agentRole": thread.get("agentRole"),
        },
        "goal": goal,
        "goalError": goal_error,
        "latestTurn": summarize_turn(latest, item_limit) if latest else None,
        "previousTurn": summarize_turn(previous, 0) if previous else None,
    }


def quoted(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def duration_label(milliseconds: int) -> str:
    return "<1ms" if milliseconds == 0 else f"{milliseconds}ms"


def bounded_collab_states(states: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        thread_id: {
            "status": state.get("status") if isinstance(state, dict) else state
        }
        for thread_id, state in states.items()
    }


def collab_state_statuses(states: dict[str, Any]) -> dict[str, Any]:
    return {
        thread_id: state.get("status") if isinstance(state, dict) else state
        for thread_id, state in states.items()
    }


def turn_line(label: str, turn: dict[str, Any]) -> str:
    timestamp = turn.get("completedAt") or turn.get("startedAt")
    completed_ago = turn.get("completedAgoSeconds")
    started_ago = turn.get("startedAgoSeconds")
    age = f"ended={completed_ago}s" if completed_ago is not None else f"started={started_ago}s"
    fields = [
        label,
        str(turn.get("status") or "unknown"),
        str(turn.get("id") or "-"),
        format_time(timestamp) if timestamp is not None else "-",
        age if completed_ago is not None or started_ago is not None else "started=-",
    ]
    if turn.get("itemsView") is not None:
        fields.append(f"view={turn['itemsView']}")
    if turn.get("durationMs") is not None:
        fields.append(f"duration={duration_label(turn['durationMs'])}")
    return "\t".join(fields)


def item_line(prefix: str, item: dict[str, Any]) -> str:
    kind = item["type"]
    status = item.get("status")
    label = f"{prefix}{kind}" + (f":{status}" if status else "")
    if kind in {"userMessage", "agentMessage", "hookPrompt", "plan"}:
        phase = item.get("phase")
        if phase:
            label += f":{phase}"
        value = item.get("text", "")
    elif kind == "reasoning":
        value = item.get("summary", [])
    elif kind == "commandExecution":
        value = item.get("command", "")
    elif kind == "fileChange":
        value = [change.get("path") for change in item.get("changes", [])]
    elif kind == "mcpToolCall":
        value = f"{item.get('server') or '-'}:{item.get('tool') or '-'}"
    elif kind == "dynamicToolCall":
        namespace = item.get("namespace")
        value = f"{namespace + ':' if namespace else ''}{item.get('tool') or '-'}"
    elif kind == "collabAgentToolCall":
        value = {
            "tool": item.get("tool"),
            "sender": item.get("senderThreadId"),
            "receivers": item.get("receiverThreadIds", []),
            "states": collab_state_statuses(item.get("agentsStates", {})),
        }
    elif kind == "subAgentActivity":
        value = {
            "kind": item.get("kind"),
            "thread": item.get("agentThreadId"),
            "path": item.get("agentPath"),
        }
    elif kind == "webSearch":
        value = item.get("query") or item.get("action")
    elif kind in {"imageView", "imageGeneration"}:
        value = item.get("path")
    elif kind in {"enteredReviewMode", "exitedReviewMode"}:
        value = item.get("review")
    else:
        value = None

    fields = [label]
    if value is not None:
        fields.append(quoted(value))
    if kind == "sleep" and item.get("durationMs") is not None:
        fields.append(f"requested={duration_label(item['durationMs'])}")
    elif item.get("durationMs") is not None:
        fields.append(f"duration={duration_label(item['durationMs'])}")
    if kind == "commandExecution":
        if item.get("exitCode") is not None:
            fields.append(f"exit={item['exitCode']}")
        if item.get("cwd") is not None:
            fields.append(f"cwd={quoted(item['cwd'])}")
    elif kind == "mcpToolCall" and item.get("error") is not None:
        fields.append(f"error={quoted(item['error'])}")
    elif kind == "dynamicToolCall" and item.get("success") is not None:
        fields.append(f"success={str(item['success']).lower()}")
    return "\t".join(fields)


def format_inspection(inspection: dict[str, Any]) -> str:
    thread = inspection["thread"]
    status = thread.get("status", {"type": "unknown"})
    loaded = "loaded" if thread.get("loaded") else "not-loaded"
    lines = [f"thread\t{loaded}\t{status_name(status)}\t{thread.get('id') or '-'}"]
    metadata = {
        key: thread.get(key)
        for key in ("name", "agentNickname", "agentRole", "cwd")
        if thread.get(key) is not None
    }
    if metadata:
        lines.append(
            "meta\t"
            + "\t".join(f"{key}={quoted(value)}" for key, value in metadata.items())
        )
    active_flags = status.get("activeFlags") or []
    if active_flags:
        lines.append("flags\t" + ",".join(active_flags))
    goal = inspection.get("goal")
    if inspection.get("goalError"):
        lines.append(f"goal\tunavailable\t{quoted(inspection['goalError'])}")
    elif goal is None:
        lines.append("goal\tnone")
    else:
        lines.append(
            "\t".join(
                [
                    "goal",
                    str(goal.get("status") or "unknown"),
                    f"tokens={goal.get('tokensUsed', 0)}",
                    f"budget={goal.get('tokenBudget') if goal.get('tokenBudget') is not None else '-'}",
                    f"time={goal.get('timeUsedSeconds', 0)}s",
                ]
            )
        )
        lines.append(f"objective\t{quoted(goal.get('objective', ''))}")

    latest = inspection.get("latestTurn")
    if latest is not None:
        lines.append(turn_line("latest", latest))
        if latest.get("error") is not None:
            lines.append(f"latest:error\t{quoted(latest['error'])}")
        lines.extend(item_line("", item) for item in latest.get("items", []))
    previous = inspection.get("previousTurn")
    if previous is not None:
        lines.append(turn_line("previous", previous))
        if previous.get("error") is not None:
            lines.append(f"previous:error\t{quoted(previous['error'])}")
        lines.extend(
            item_line("previous:", item)
            for item in previous.get("items", [])
            if item.get("type") == "agentMessage"
        )
    return "\n".join(lines)
