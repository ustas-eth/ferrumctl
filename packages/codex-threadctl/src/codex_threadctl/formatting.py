from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def quoted(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def format_time(timestamp: int | None) -> str:
    if timestamp is None:
        return "-"
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def duration_label(milliseconds: int) -> str:
    return "<1ms" if milliseconds == 0 else f"{milliseconds}ms"


def status_name(status: dict[str, Any]) -> str:
    return str(status.get("type", "unknown"))


def turn_line(label: str, turn: dict[str, Any]) -> str:
    timestamp = turn.get("completedAt") or turn.get("startedAt")
    completed_ago = turn.get("completedAgoSeconds")
    started_ago = turn.get("startedAgoSeconds")
    age = f"ended={completed_ago}s" if completed_ago is not None else f"started={started_ago}s"
    fields = [
        label,
        str(turn.get("status") or "unknown"),
        str(turn.get("id") or "-"),
        format_time(timestamp),
        age if completed_ago is not None or started_ago is not None else "started=-",
    ]
    if turn.get("itemsView") is not None:
        fields.append(f"view={turn['itemsView']}")
    if turn.get("durationMs") is not None:
        fields.append(f"duration={duration_label(turn['durationMs'])}")
    return "\t".join(fields)


def item_line(item: dict[str, Any]) -> str:
    kind = item["type"]
    status = item.get("status")
    label = kind + (f":{status}" if status else "")
    if kind in {"userMessage", "agentMessage", "hookPrompt", "plan"}:
        if item.get("phase"):
            label += f":{item['phase']}"
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
            "states": {
                thread_id: state.get("status") if isinstance(state, dict) else state
                for thread_id, state in item.get("agentsStates", {}).items()
            },
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
    if item.get("durationMs") is not None:
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
    status = thread.get("status") or {"type": "unknown"}
    loaded = "loaded" if thread.get("loaded") else "not-loaded"
    lines = [f"thread\t{loaded}\t{status_name(status)}\t{thread.get('id') or '-'}"]

    metadata = {
        key: thread.get(key)
        for key in (
            "name",
            "agentNickname",
            "agentRole",
            "parentThreadId",
            "forkedFromId",
            "cwd",
            "source",
        )
        if thread.get(key) is not None
    }
    if metadata:
        lines.append(
            "meta\t" + "\t".join(f"{key}={quoted(value)}" for key, value in metadata.items())
        )
    flags = status.get("activeFlags") or []
    if flags:
        lines.append("flags\t" + ",".join(flags))

    context = inspection.get("context")
    if context is not None:
        lines.append(
            "\t".join(
                [
                    "context",
                    f"used={context['usedTokens']}",
                    f"window={context['windowTokens']}",
                    f"left={context['percentLeft']}%",
                    f"observed={format_time(context['observedAt'])}",
                    f"age={context['observedAgoSeconds']}s",
                ]
            )
        )
    elif inspection.get("contextError"):
        lines.append(f"context\tunavailable\t{quoted(inspection['contextError'])}")
    compaction = inspection.get("compaction")
    if compaction is not None:
        window = compaction.get("windowNumber")
        lines.append(
            "\t".join(
                [
                    "compaction",
                    f"window={window if window is not None else '-'}",
                    f"last={format_time(compaction['lastAt'])}",
                    f"age={compaction['lastAgoSeconds']}s",
                ]
            )
        )

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
        lines.extend(item_line(item) for item in latest.get("items", []))
    previous = inspection.get("previousTurn")
    if previous is not None:
        lines.append(turn_line("previous", previous))
        if previous.get("error") is not None:
            lines.append(f"previous:error\t{quoted(previous['error'])}")
        lines.extend(f"previous:{item_line(item)}" for item in previous.get("items", []))
    return "\n".join(lines)


def message_preview(text: str, limit: int = 160) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def format_messages(messages: list[dict[str, Any]]) -> str:
    lines = []
    for message in messages:
        timestamp = message.get("completedAt") or message.get("startedAt")
        lines.append(
            "\t".join(
                [
                    message["role"],
                    format_time(timestamp),
                    str(message.get("turnId") or "-"),
                    str(message.get("itemId") or "-"),
                    str(message.get("phase") or "-"),
                    quoted(message_preview(message.get("text", ""))),
                ]
            )
        )
    return "\n".join(lines)
