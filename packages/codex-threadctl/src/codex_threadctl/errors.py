from __future__ import annotations

import json
from typing import Any


class ThreadctlError(Exception):
    """Expected command failure."""


class OperationError(ThreadctlError):
    """An operation with a known partial or uncertain outcome."""

    def __init__(self, message: str, *, code: str, outcome: str, **details: Any):
        super().__init__(message)
        self.result = {"code": code, "outcome": outcome, **details}


class AppServerResponseError(ThreadctlError):
    """App-server rejected a request with a JSON-RPC error response."""

    def __init__(self, payload: Any):
        self.payload = payload
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            message = payload["message"]
        else:
            message = json.dumps(payload, separators=(",", ":"))
        super().__init__(message)


class ThreadNotLoaded(ThreadctlError):
    """The selected app-server does not have the target loaded."""


class ThreadStateError(ThreadctlError):
    """The requested operation does not match the current thread state."""


class DirectInputUnsupported(ThreadStateError):
    """The target's owner does not permit direct app-server input."""


class DeliveryUncertain(ThreadctlError):
    """An input request was submitted but its outcome could not be confirmed."""

    def __init__(self, turn_id: str | None, client_message_id: str):
        self.turn_id = turn_id
        self.client_message_id = client_message_id
        target = f" for turn {turn_id}" if turn_id is not None else ""
        super().__init__(
            f"input outcome is uncertain{target}; "
            f"client message id {client_message_id}"
        )


class NotificationUncertain(ThreadctlError):
    """An advisory item may have been accepted before the connection failed."""

    def __init__(self, item_id: str):
        self.item_id = item_id
        super().__init__(
            "notification outcome is uncertain; "
            f"agent message id {item_id}"
        )


def error_record(exc: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {"code": "commandFailed", "outcome": "failed"}
    if isinstance(exc, OperationError):
        result.update(exc.result)
    elif isinstance(exc, DeliveryUncertain):
        result.update(
            code="deliveryUncertain", outcome="uncertain",
            turnId=exc.turn_id, clientMessageId=exc.client_message_id,
        )
    elif isinstance(exc, NotificationUncertain):
        result.update(code="notificationUncertain", outcome="uncertain", itemId=exc.item_id)
    elif isinstance(exc, AppServerResponseError):
        result.update(code="appServerRejected", outcome="rejected")
        if isinstance(exc.payload, dict) and "code" in exc.payload:
            result["rpcCode"] = exc.payload["code"]
    elif isinstance(exc, ThreadNotLoaded):
        result.update(code="threadNotLoaded", outcome="notSubmitted")
    elif isinstance(exc, DirectInputUnsupported):
        result.update(code="directInputUnsupported", outcome="rejected")
    elif isinstance(exc, ThreadStateError):
        result.update(code="threadStateConflict", outcome="rejected")
    result["message"] = str(exc)
    return result
