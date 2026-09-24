"""Caller-local TOML passed as native app-server configuration overrides."""
from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

from .errors import ThreadctlError


def read_config_file(filename: str | None) -> dict[str, Any] | None:
    if filename is None:
        return None
    try:
        with Path(filename).expanduser().open("rb") as source:
            config = tomllib.load(source)
        # TOML also permits dates and non-finite floats; the RPC accepts JSON.
        json.dumps(config, allow_nan=False)
    except (OSError, ValueError, TypeError) as exc:
        raise ThreadctlError(f"cannot load config file {filename}: {exc}") from exc
    if "profile" in config or "profiles" in config:
        raise ThreadctlError(
            "--config-file accepts Codex settings, not profile selectors or "
            "legacy [profiles] tables; supply the profile's settings directly"
        )
    return config


def request_config(
    config: dict[str, Any] | None,
    *,
    model: str | None = None,
    model_provider: str | None = None,
    approval_policy: str | None = None,
    sandbox: str | None = None,
    permission_profile: str | None = None,
    effort: str | None = None,
) -> dict[str, Any]:
    result = dict(config or {})
    # Typed RPC fields win over file values. Remove competing legacy permission
    # selectors as well; leaving sandbox_mode can defeat a named profile.
    for key, value in (
        ("model", model), ("model_provider", model_provider),
        ("approval_policy", approval_policy),
    ):
        if value is not None:
            result.pop(key, None)
    if sandbox is not None or permission_profile is not None:
        result.pop("sandbox_mode", None)
        result.pop("default_permissions", None)
    if effort is not None:
        result["model_reasoning_effort"] = effort
    return result
