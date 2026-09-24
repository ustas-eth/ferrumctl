"""Settings observations retain their source rather than implying live execution."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .context import reverse_lines, timestamp_seconds


SERVER_SETTINGS = (
    "model", "modelProvider", "reasoningEffort", "cwd", "approvalPolicy",
    "approvalsReviewer", "sandbox", "activePermissionProfile",
)


def reported_settings(response: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "source": source,
        "observedAt": int(time.time()),
        **{key: response[key] for key in SERVER_SETTINGS if key in response},
    }


def read_recorded_settings(path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not path:
        return None, "no local rollout path is available"
    fields = {
        "turn_id": "turnId", "model": "model", "effort": "reasoningEffort",
        "cwd": "cwd", "approval_policy": "approvalPolicy",
        "approvals_reviewer": "approvalsReviewer", "sandbox_policy": "sandbox",
        "permission_profile": "permissionProfile",
        "active_permission_profile": "activePermissionProfile",
    }
    try:
        for line in reverse_lines(Path(path)):
            if b'"turn_context"' not in line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or record.get("type") != "turn_context":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            return {
                "source": "local-rollout",
                "observedAt": timestamp_seconds(record.get("timestamp")),
                **{dest: payload[src] for src, dest in fields.items() if src in payload},
            }, None
    except OSError as exc:
        return None, f"local rollout settings unavailable: {exc}"
    return None, "no turn settings have been recorded"


def settings_overrides(
    *, model: str | None = None, effort: str | None = None,
    permission_profile: str | None = None, approval_policy: str | None = None,
) -> dict[str, str]:
    return {key: value for key, value in {
        "model": model, "effort": effort, "permissions": permission_profile,
        "approvalPolicy": approval_policy,
    }.items() if value is not None}


def unconfirmed_settings(requested: dict[str, str], response: dict[str, Any]) -> list[str]:
    profile = response.get("activePermissionProfile")
    observed = {
        "model": response.get("model"),
        "effort": response.get("reasoningEffort"),
        "permissions": profile.get("id") if isinstance(profile, dict) else None,
        "approvalPolicy": response.get("approvalPolicy"),
    }
    return [key for key, value in requested.items() if observed.get(key) != value]
