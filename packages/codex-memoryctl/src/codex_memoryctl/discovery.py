from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import Any

from .errors import MemoryctlError
from .rollouts import (
    MemoryState,
    RolloutMemory,
    TranscriptMessage,
    distinct_session_meta_thread_id,
)

SNIPPET_ANCHORS = 3
SNIPPET_CHARACTERS = 240


@dataclass(frozen=True)
class SearchCandidate:
    checkpoint: MemoryState | None
    match_count: int
    closest_line_distance: int | None
    messages: tuple[TranscriptMessage, ...]
    matched_line_numbers: frozenset[int]

    def metadata(self) -> dict[str, Any]:
        return {
            "checkpoint": (
                {
                    **self.checkpoint.metadata(),
                    "lineNumber": self.checkpoint.line_number,
                }
                if self.checkpoint is not None
                else None
            ),
            "matchCount": self.match_count,
            "shownMatchCount": sum(
                value.line_number in self.matched_line_numbers
                for value in self.messages
            ),
            "closestLineDistance": self.closest_line_distance,
            "messages": [
                message_metadata(
                    value,
                    matched=value.line_number in self.matched_line_numbers,
                )
                for value in self.messages
            ],
        }


def compact_text(value: str) -> str:
    shown = " ".join(value.split())
    if len(shown) <= SNIPPET_CHARACTERS:
        return shown
    return shown[: SNIPPET_CHARACTERS - 1] + "…"


def message_metadata(
    message: TranscriptMessage,
    *,
    matched: bool,
) -> dict[str, Any]:
    return {
        "lineNumber": message.line_number,
        "timestamp": message.timestamp,
        "role": message.role,
        "turnId": message.turn_id,
        "matched": matched,
        "text": compact_text(message.text),
    }


def _tokenize(query: str) -> tuple[str, ...]:
    tokens = tuple(re.findall(r"\w+", query.casefold()))
    if not tokens:
        raise MemoryctlError("token query must contain a letter or number")
    return tokens


def _compile_regex(query: str) -> re.Pattern[str]:
    try:
        return re.compile(query, re.IGNORECASE)
    except re.error as exc:
        raise MemoryctlError(f"invalid search regular expression: {exc}") from exc


def _matching_messages(
    messages: list[TranscriptMessage],
    query: str,
    mode: str,
) -> list[int]:
    if mode == "tokens":
        tokens = _tokenize(query)
        message_tokens = [
            frozenset(re.findall(r"\w+", value.text.casefold())) for value in messages
        ]
        combined = frozenset().union(*message_tokens)
        if not all(token in combined for token in tokens):
            return []
        return [
            index
            for index, available in enumerate(message_tokens)
            if any(token in available for token in tokens)
        ]
    if mode == "phrase":
        folded = query.casefold()
        return [
            index
            for index, message in enumerate(messages)
            if folded in message.text.casefold()
        ]
    if mode == "regex":
        expression = _compile_regex(query)
        return [
            index
            for index, message in enumerate(messages)
            if expression.search(message.text) is not None
        ]
    raise MemoryctlError(f"unknown search mode: {mode}")


def _context_messages(
    messages: list[TranscriptMessage],
    matches: list[int],
    context: int,
) -> tuple[TranscriptMessage, ...]:
    anchors = matches[-SNIPPET_ANCHORS:]
    selected: set[int] = set()
    for anchor in anchors:
        selected.update(
            range(
                max(0, anchor - context),
                min(len(messages), anchor + context + 1),
            )
        )
    return tuple(messages[index] for index in sorted(selected))


def search_rollout(
    rollout: RolloutMemory,
    query: str,
    *,
    mode: str,
    limit: int,
    context: int,
) -> dict[str, Any]:
    checkpoints = [
        state
        for state in rollout.states
        if state.origin == "checkpoint" and state.line_number is not None
    ]
    checkpoint_lines = [int(state.line_number) for state in checkpoints]
    grouped: dict[int | None, list[TranscriptMessage]] = {}
    for message in rollout.messages:
        index = bisect.bisect_right(checkpoint_lines, message.line_number)
        key = index if index < len(checkpoints) else None
        grouped.setdefault(key, []).append(message)

    candidates: list[SearchCandidate] = []
    for checkpoint_index, messages in grouped.items():
        matches = _matching_messages(messages, query, mode)
        if not matches:
            continue
        checkpoint = checkpoints[checkpoint_index] if checkpoint_index is not None else None
        closest = (
            int(checkpoint.line_number) - messages[matches[-1]].line_number
            if checkpoint is not None and checkpoint.line_number is not None
            else None
        )
        candidates.append(
            SearchCandidate(
                checkpoint=checkpoint,
                match_count=len(matches),
                closest_line_distance=closest,
                messages=_context_messages(messages, matches, context),
                matched_line_numbers=frozenset(
                    messages[index].line_number for index in matches
                ),
            )
        )

    candidates.sort(
        key=lambda value: (
            value.checkpoint is not None,
            value.closest_line_distance
            if value.closest_line_distance is not None
            else 0,
            -(value.checkpoint.checkpoint_index or 0)
            if value.checkpoint is not None
            else 0,
        )
    )
    selected = candidates if limit == 0 else candidates[:limit]
    return {
        "threadId": rollout.thread_id,
        "sessionMetaThreadId": distinct_session_meta_thread_id(
            rollout.thread_id,
            rollout.session_meta_thread_id,
        ),
        "rolloutPath": str(rollout.path),
        "query": query,
        "matchMode": mode,
        "messageCount": len(rollout.messages),
        "checkpointCount": len(checkpoints),
        "candidateCount": len(candidates),
        "candidates": [value.metadata() for value in selected],
    }
