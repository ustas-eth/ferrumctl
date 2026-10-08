from __future__ import annotations

import uuid


def agent_message_id(stable_key: str | None = None) -> str:
    """Use native item syntax, optionally preserving a caller's stable identity."""
    value = (
        uuid.uuid4()
        if stable_key is None
        else uuid.uuid5(uuid.NAMESPACE_URL, stable_key)
    )
    return f"amsg_{value}"
