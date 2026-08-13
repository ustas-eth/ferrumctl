from __future__ import annotations


class WakectlError(RuntimeError):
    pass


class EventDeliveryUncertain(WakectlError):
    """An event was injected, but its wake outcome was not confirmed."""

    def __init__(
        self,
        item_id: str,
        *,
        turn_id: str | None = None,
        reason: str | None = None,
    ):
        self.item_id = item_id
        self.turn_id = turn_id
        detail = f"; {reason}" if reason else ""
        super().__init__(f"event outcome is uncertain; agent message id {item_id}{detail}")
