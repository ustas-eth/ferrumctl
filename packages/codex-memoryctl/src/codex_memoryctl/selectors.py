from __future__ import annotations

from dataclasses import dataclass

from .errors import MemoryctlError
from .rollouts import MemoryState, RolloutMemory


@dataclass(frozen=True)
class StateReference:
    source: str
    selector: str


def parse_state_reference(value: str) -> StateReference:
    if "@" not in value:
        return StateReference(value, "latest")
    source, selector = value.rsplit("@", 1)
    if not source or not selector:
        raise MemoryctlError(
            "state reference must use SOURCE@latest, SOURCE@window:N, "
            "SOURCE@index:N, or SOURCE@sha256:PREFIX"
        )
    return StateReference(source, selector)


def _number(value: str, label: str, *, allow_zero: bool) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise MemoryctlError(f"{label} must be a positive integer") from exc
    if number < 0 or (number == 0 and not allow_zero):
        qualification = "non-negative" if allow_zero else "positive"
        raise MemoryctlError(f"{label} must be a {qualification} integer")
    return number


def select_state(
    rollout: RolloutMemory,
    selector: str,
    *,
    require_checkpoint: bool = False,
) -> MemoryState:
    states = list(rollout.states)
    if selector == "latest":
        checkpoints = [state for state in states if state.origin == "checkpoint"]
        matches = checkpoints[-1:] or states[-1:]
    elif selector.startswith("window:"):
        number = _number(
            selector.removeprefix("window:"), "window", allow_zero=True
        )
        matches = [state for state in states if state.window_number == number]
    elif selector.startswith("index:"):
        number = _number(
            selector.removeprefix("index:"), "index", allow_zero=False
        )
        matches = [state for state in states if state.checkpoint_index == number]
    elif selector.startswith("sha256:"):
        prefix = selector.removeprefix("sha256:").lower()
        if not prefix or any(char not in "0123456789abcdef" for char in prefix):
            raise MemoryctlError("sha256 selector must contain hexadecimal characters")
        matches = [
            state
            for state in states
            if state.memory_id.removeprefix("sha256:").startswith(prefix)
        ]
        distinct = {state.memory_id for state in matches}
        if len(distinct) > 1:
            raise MemoryctlError(f"sha256 selector is ambiguous: {prefix}")
    else:
        raise MemoryctlError(
            "unknown state selector; use latest, window:N, index:N, or sha256:PREFIX"
        )

    if require_checkpoint:
        matches = [state for state in matches if state.origin == "checkpoint"]
    if matches:
        matches = matches[-1:]
    if not matches:
        qualification = " checkpoint" if require_checkpoint else ""
        raise MemoryctlError(
            f"memory{qualification} not found in {rollout.thread_id}: {selector}"
        )
    return matches[-1]
