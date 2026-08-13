from __future__ import annotations

import argparse
from typing import Any

from .errors import WakectlError


_CMD_OPTIONS = {
    "--allow-active",
    "--endpoint",
    "--input",
    "--json",
    "--notify-active",
    "--resume",
    "--state",
    "--timeout",
    "--to",
    "--tree",
}


def event_action(*, notify_active: bool = False, resume: bool = False) -> dict[str, Any]:
    return {
        "type": "event",
        **({"notifyActive": True} if notify_active else {}),
        **({"resume": True} if resume else {}),
    }


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
    return event_action(notify_active=notify_active, resume=resume)
