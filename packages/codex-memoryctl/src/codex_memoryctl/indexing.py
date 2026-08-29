from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from .errors import MemoryctlError
from .rollouts import MemoryState, RolloutMemory


UTC_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class TimeBoundary:
    raw: str
    instant: datetime
    date_only: bool


@dataclass(frozen=True)
class IndexSelection:
    states: tuple[MemoryState, ...]
    matching_positions: tuple[int, ...]
    selected_positions: tuple[int, ...]

    @property
    def selected_states(self) -> tuple[MemoryState, ...]:
        return tuple(self.states[position] for position in self.selected_positions)


def parse_time_boundary(value: str) -> TimeBoundary:
    try:
        if UTC_DATE_RE.fullmatch(value):
            parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
            return TimeBoundary(
                value,
                datetime.combine(parsed_date, time.min, tzinfo=timezone.utc),
                True,
            )
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryctlError("must be a UTC date or RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryctlError("timestamp must include a UTC offset")
    return TimeBoundary(value, parsed.astimezone(timezone.utc), False)


def _observed_at(state: MemoryState) -> datetime:
    if state.observed_at is None:
        raise MemoryctlError(
            f"checkpoint index {state.checkpoint_index} has no timestamp; "
            "use index bounds instead"
        )
    try:
        parsed = datetime.fromisoformat(state.observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryctlError(
            f"checkpoint index {state.checkpoint_index} has an invalid timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MemoryctlError(
            f"checkpoint index {state.checkpoint_index} has a timestamp without an offset"
        )
    return parsed.astimezone(timezone.utc)


def select_checkpoints(
    states: list[MemoryState],
    *,
    from_index: int | None,
    to_index: int | None,
    since: TimeBoundary | None,
    until: TimeBoundary | None,
    limit: int,
) -> IndexSelection:
    ordered = tuple(sorted(states, key=lambda state: state.checkpoint_index or 0))
    if not ordered:
        raise MemoryctlError("thread has no portable memory checkpoints")
    if from_index is not None and to_index is not None and from_index > to_index:
        raise MemoryctlError("--from-index must be less than or equal to --to-index")
    if since is not None and until is not None:
        until_edge = (
            until.instant + timedelta(days=1) if until.date_only else until.instant
        )
        if (
            until.date_only and since.instant >= until_edge
        ) or (
            not until.date_only and since.instant > until_edge
        ):
            raise MemoryctlError("--since must be earlier than or equal to --until")

    matching: list[int] = []
    for position, state in enumerate(ordered):
        index = state.checkpoint_index
        if index is None:
            raise MemoryctlError("portable checkpoint has no checkpoint index")
        if from_index is not None and index < from_index:
            continue
        if to_index is not None and index > to_index:
            continue
        if since is not None or until is not None:
            observed_at = _observed_at(state)
            if since is not None and observed_at < since.instant:
                continue
            if until is not None:
                if until.date_only:
                    if observed_at >= until.instant + timedelta(days=1):
                        continue
                elif observed_at > until.instant:
                    continue
        matching.append(position)

    if not matching:
        raise MemoryctlError("no portable checkpoints match the selected range")
    selected = matching if limit == 0 else matching[-limit:]
    return IndexSelection(ordered, tuple(matching), tuple(selected))


def uncompacted_message_count(rollout: RolloutMemory) -> int:
    last_compaction_line = rollout.last_compaction_line
    if last_compaction_line is None:
        checkpoint_lines = [
            state.line_number
            for state in rollout.states
            if state.origin == "checkpoint" and state.line_number is not None
        ]
        last_compaction_line = max(checkpoint_lines, default=None)
    if last_compaction_line is None:
        return len(rollout.messages)
    return sum(
        message.line_number > last_compaction_line
        for message in rollout.messages
    )
