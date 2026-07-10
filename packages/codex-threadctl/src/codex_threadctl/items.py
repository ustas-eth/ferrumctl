from __future__ import annotations

from typing import Any

from .errors import ThreadctlError


def summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    kind = item.get("type", "unknown")
    summary: dict[str, Any] = {"type": kind}
    for key in ("id", "status", "durationMs"):
        if item.get(key) is not None:
            summary[key] = item[key]

    if kind == "userMessage":
        summary["text"] = message_text(item)
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
    elif kind in {"enteredReviewMode", "exitedReviewMode"}:
        summary["review"] = item.get("review")
    return summary


def bounded_collab_states(states: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        thread_id: {
            "status": state.get("status") if isinstance(state, dict) else state
        }
        for thread_id, state in states.items()
    }


def message_text(item: dict[str, Any]) -> str:
    if item.get("type") == "agentMessage":
        return str(item.get("text", ""))
    if item.get("type") == "userMessage":
        return "\n".join(
            entry.get("text", "")
            for entry in item.get("content", [])
            if entry.get("type") == "text"
        )
    raise ThreadctlError(f"item is not a conversation message: {item.get('type', 'unknown')}")


def message_record(turn: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "turnId": turn.get("id"),
        "itemId": item.get("id"),
        "role": "user" if item.get("type") == "userMessage" else "agent",
        "phase": item.get("phase"),
        "text": message_text(item),
        "turnStatus": turn.get("status"),
        "startedAt": turn.get("startedAt"),
        "completedAt": turn.get("completedAt"),
    }
