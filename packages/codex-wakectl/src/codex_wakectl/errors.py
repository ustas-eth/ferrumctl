from __future__ import annotations

from typing import Any


class WakectlError(RuntimeError):
    pass


class EventDeliveryUncertain(WakectlError):
    """Event acceptance or its subsequent attention could not be confirmed."""

    def __init__(
        self,
        item_id: str,
        *,
        turn_id: str | None = None,
        reason: str | None = None,
        loading: dict[str, Any] | None = None,
    ):
        self.item_id = item_id
        self.turn_id = turn_id
        self.loading = loading
        detail = f"; {reason}" if reason else ""
        super().__init__(f"event outcome is uncertain; agent message id {item_id}{detail}")
