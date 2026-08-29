from __future__ import annotations

from .rollouts import MemoryState, memory_ref


def format_state(state: MemoryState) -> str:
    fields = [
        state.origin,
        state.observed_at or "-",
        memory_ref(state.memory_id),
        f"bytes={state.payload_bytes}",
        f"visible={'yes' if state.visible else 'no'}",
    ]
    if state.checkpoint_index is not None:
        fields.append(f"index={state.checkpoint_index}")
    if state.window_number is not None:
        fields.append(f"window={state.window_number}")
    if state.retained_items is not None:
        fields.append(f"retained={state.retained_items}")
    if state.model:
        fields.append(f"model={state.model}")
    return "\t".join(fields)
