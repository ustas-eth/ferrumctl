from __future__ import annotations

import json
from typing import Any


class ThreadctlError(Exception):
    """Expected command failure."""


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
