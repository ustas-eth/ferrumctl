"""Apply settings at the server's loading or subsequent-turn boundary."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import websockets

from .appserver import AppServer, list_loaded, require_loaded, require_object
from .errors import AppServerResponseError, OperationError, ThreadctlError, ThreadStateError
from .config_input import request_config
from .settings import reported_settings, settings_overrides, unconfirmed_settings
from .recovery import (
    database, public_recovery, read_recovery, recovery_config, remember_after_operation,
)


async def resume_thread(
    app: AppServer,
    thread_id: str,
    *,
    continue_goal: bool = False,
    model: str | None = None,
    effort: str | None = None,
    permission_profile: str | None = None,
    approval_policy: str | None = None,
    config_overrides: dict[str, Any] | None = None,
    recovery_state: Path | None = None,
    remember_config: bool = True,
) -> dict[str, Any]:
    if not continue_goal:
        raise ThreadStateError(
            "resume can continue an active goal without input; "
            "pass --continue-goal to acknowledge this"
        )
    requested = settings_overrides(
        model=model, effort=effort, permission_profile=permission_profile,
        approval_policy=approval_policy,
    )
    config = request_config(
        config_overrides, model=model, effort=effort,
        permission_profile=permission_profile, approval_policy=approval_policy,
    )
    loaded = (thread_id in await list_loaded(app)
              if requested or config or recovery_state is not None else False)
    if (requested or config) and loaded:
        if config_overrides:
            raise ThreadStateError(
                "thread is already loaded; config-file overrides apply only on cold loading. "
                "Use configure for model, effort, approval policy, or an existing permission profile; "
                "recovery --config-file replaces saved supplementary overrides for a later cold load, "
                "not live settings"
            )
        raise ThreadStateError(
            "thread is already loaded; use configure for model, effort, approval policy, "
            "or an existing permission profile"
        )
    recovery = None
    record = None
    save_requested = (not loaded and recovery_state is not None and config_overrides is not None
                      and remember_config and bool(recovery_config(config_overrides)))
    if recovery_state is not None and not loaded:
        record = read_recovery(recovery_state, app.endpoint, thread_id)
        saved = record["config"] if record else {}
        # Like native request config, nested values are replaced as whole values.
        config = request_config(
            {**saved, **(config_overrides or {})}, model=model, effort=effort,
            permission_profile=permission_profile, approval_policy=approval_policy,
        )
        if remember_config:
            recovery_config(config)
        recovery = public_recovery(recovery_state, app.endpoint, thread_id, record)
        recovery["outcome"] = "submitted" if saved else "notFound"
        recovery["submittedKeys"] = sorted(
            key for key in saved if key not in (config_overrides or {})
        )
        if save_requested:
            with database(recovery_state, write=True):
                pass
    params: dict[str, Any] = {"threadId": thread_id, "excludeTurns": True, **requested}
    params.pop("effort", None)
    if config:
        params["config"] = config
    try:
        result = require_object(
            await app.request("thread/resume", params), "thread/resume result",
        )
        thread = require_object(result.get("thread"), "thread/resume thread")
    except AppServerResponseError:
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise OperationError(
            "resume outcome is uncertain; inspect the thread before retrying",
            code="resumeUncertain", outcome="uncertain", threadId=thread_id,
        ) from exc
    settings = reported_settings(result, "thread/resume")
    missing = unconfirmed_settings(requested, result)
    if missing:
        raise OperationError(
            "thread resumed but requested settings were not confirmed: " + ", ".join(missing),
            code="resumeSettingsUnconfirmed", outcome="partial", threadId=thread_id,
            requestedSettings=requested, settings=settings,
        )
    if save_requested and not loaded:
        saved_result = remember_after_operation(
            recovery_state, app.endpoint, thread_id, config, "was resumed",
            expected_revision=record["revision"] if record else None,
        )
        recovery = {**(recovery or {}), "saved": saved_result}
    return {
        **thread, "settings": settings,
        **({"configRequest": {"keys": sorted(config)}} if config_overrides is not None or config else {}),
        **({"recovery": recovery} if recovery is not None else {}),
    }


async def configure_thread(
    app: AppServer,
    thread_id: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    permission_profile: str | None = None,
    approval_policy: str | None = None,
) -> dict[str, Any]:
    requested = settings_overrides(
        model=model, effort=effort, permission_profile=permission_profile,
        approval_policy=approval_policy,
    )
    if not requested:
        raise ThreadStateError("configure requires at least one setting")
    await require_loaded(app, thread_id)
    try:
        require_object(
            await app.request("thread/settings/update", {"threadId": thread_id, **requested}),
            "thread/settings/update result",
        )
    except AppServerResponseError:
        raise
    except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
        raise OperationError(
            "settings update outcome is uncertain; inspect the thread before retrying",
            code="settingsUpdateUncertain", outcome="uncertain", threadId=thread_id,
            requestedSettings=requested,
        ) from exc
    return {
        "threadId": thread_id, "outcome": "accepted",
        "appliesTo": "subsequentTurns", "requestedSettings": requested,
    }
