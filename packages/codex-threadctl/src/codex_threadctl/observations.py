from __future__ import annotations

from pathlib import Path
from typing import Any

from .context import RELEVANT_RECORD_TYPES, context_from_records, read_context_state, rollout_records
from .rollout_io import open_rollout, rollout_path
from .settings import read_recorded_settings, recorded_settings_from_record


def read_rollout_observations(path: str | None) -> tuple[
    dict[str, Any] | None, dict[str, Any] | None, str | None, dict[str, Any] | None, str | None,
]:
    selected = rollout_path(Path(path)) if path else None
    if selected is None or not selected.name.endswith(".zst"):
        plain = str(selected) if selected is not None else None
        context, compaction = read_context_state(plain)
        settings, settings_error = read_recorded_settings(plain)
        return context, compaction, None, settings, settings_error

    latest_settings = None
    try:
        with open_rollout(selected, "rb") as stream:
            def context_records():
                nonlocal latest_settings
                for record in rollout_records(stream, (*RELEVANT_RECORD_TYPES, b'"turn_context"')):
                    if record.get("type") == "turn_context":
                        latest_settings = record
                    else:
                        yield record

            context, compaction = context_from_records(context_records(), newest_first=False)
    except OSError as exc:
        error = f"cannot read compressed rollout {selected}: {exc}"
        return None, None, error, None, error
    if latest_settings is None:
        return context, compaction, None, None, "no turn settings have been recorded"
    return context, compaction, None, recorded_settings_from_record(latest_settings), None
