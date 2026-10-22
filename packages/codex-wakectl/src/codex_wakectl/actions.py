from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from codex_threadctl.config_input import read_config_file
from codex_threadctl.recovery import default_state_path

from .errors import WakectlError


_CMD_OPTIONS = {
    "--allow-active",
    "--config-file",
    "--endpoint",
    "--input",
    "--json",
    "--notify-active",
    "--no-recovery",
    "--recovery-state",
    "--resume",
    "--state",
    "--timeout",
    "--to",
    "--tree",
}


def event_action(
    *, notify_active: bool = False, resume: bool = False,
    config: dict[str, Any] | None = None,
    recovery_state: Path | None = None, no_recovery: bool = False,
) -> dict[str, Any]:
    return {
        "type": "event",
        **({"notifyActive": True} if notify_active else {}),
        **({"resume": True} if resume else {}),
        **({"resumeConfig": config} if config is not None else {}),
        **({"recoveryState": str(recovery_state.expanduser().resolve())} if recovery_state is not None else {}),
        **({"noRecovery": True} if no_recovery else {}),
    }


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Report submitted config keys without exposing the saved values."""
    action = dict(job["action"])
    if "resumeConfig" in action:
        action["configRequest"] = {"keys": sorted(action.pop("resumeConfig"))}
    return {**job, "action": action}


def input_action(
    message: str,
    *,
    allow_active: bool = False,
    legacy: bool = False,
) -> dict[str, Any]:
    return {
        "type": "input",
        "message": message,
        **({"allowActive": True} if allow_active else {}),
        **({"legacy": True} if legacy else {}),
    }


def _prepare_command(args: argparse.Namespace) -> None:
    if args.condition != "cmd":
        return
    parts = list(args.command_parts)
    try:
        separator = parts.index("--")
    except ValueError as exc:
        raise WakectlError("add cmd requires a predicate command after --") from exc
    before = parts[:separator]
    args.argv = parts[separator + 1 :]
    if not args.argv:
        raise WakectlError("add cmd requires a predicate command after --")
    if len(before) > 1:
        option = next(
            (value.partition("=")[0] for value in before[1:] if value.startswith("--")),
            None,
        )
        if option in _CMD_OPTIONS:
            raise WakectlError(f"{option} must appear before MESSAGE")
        raise WakectlError("legacy add cmd accepts one MESSAGE before --")
    if before:
        args.legacy_message = before[0]


def build_action(args: argparse.Namespace) -> dict[str, Any]:
    _prepare_command(args)
    legacy_message = getattr(args, "legacy_message", None)
    input_message = getattr(args, "input_message", None)
    allow_active = bool(getattr(args, "allow_active", False))
    notify_active = bool(getattr(args, "notify_active", False))
    resume = bool(getattr(args, "resume", False))
    config_file = getattr(args, "config_file", None)
    recovery_state = getattr(args, "recovery_state", None)
    no_recovery = bool(getattr(args, "no_recovery", False))
    if config_file and not resume:
        raise WakectlError("--config-file requires --resume")
    if (recovery_state is not None or no_recovery) and not resume:
        raise WakectlError("--recovery-state and --no-recovery require --resume")
    if recovery_state is not None and no_recovery:
        raise WakectlError("use either --recovery-state or --no-recovery")

    if legacy_message is not None and input_message is not None:
        raise WakectlError("use either legacy MESSAGE or --input, not both")
    message = input_message if input_message is not None else legacy_message
    if message is not None:
        if notify_active:
            raise WakectlError("--notify-active applies only to event wakes")
        if resume:
            raise WakectlError("--resume applies only to event wakes")
        if allow_active and input_message is not None:
            raise WakectlError(
                "scheduled --input cannot steer active work; "
                "use codex-threadctl steer for immediate intervention"
            )
        return input_action(
            message,
            allow_active=allow_active,
            legacy=legacy_message is not None,
        )

    if allow_active:
        raise WakectlError("use --notify-active for an event wake")
    return event_action(
        notify_active=notify_active, resume=resume,
        config=read_config_file(config_file),
        recovery_state=(recovery_state or default_state_path()) if resume and not no_recovery else None,
        no_recovery=no_recovery,
    )
