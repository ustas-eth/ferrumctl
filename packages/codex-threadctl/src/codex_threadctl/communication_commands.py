"""CLI selection of message role and optional attention."""
from __future__ import annotations

import argparse
import json
import sys

from .agents import resolve_thread_reference
from .appserver import AppServer, start_turn, steer_turn
from .attention import send_message
from .commands import current_identity
from .config_input import read_config_file
from .errors import ThreadctlError
from .formatting import format_loading_fields


def message_text(args: argparse.Namespace) -> str:
    if not args.stdin:
        return args.message
    if sys.stdin.isatty():
        raise ThreadctlError("--stdin requires redirected message text")
    try:
        message = sys.stdin.read()
        message.encode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ThreadctlError("could not read message text from standard input") from exc
    if not message.strip():
        raise ThreadctlError("message text from standard input must not be empty")
    return message


async def cmd_send(args: argparse.Namespace) -> int:
    if args.resume and not args.wake:
        raise ThreadctlError("send --resume requires --wake; loading may continue a goal")
    if args.config_file and not args.resume:
        raise ThreadctlError("--config-file requires --resume")
    message = message_text(args)
    author = current_identity(args.author, "--from")
    config = read_config_file(args.config_file) if args.config_file else None
    async with AppServer(args.endpoint, args.timeout) as app:
        target = await resolve_thread_reference(app, args.thread_id, tree_thread_id=args.tree)
        result = await send_message(
            app, target, author, message, wake=args.wake, resume=args.resume, config=config,
        )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        fields = [result["outcome"], target, "role=agent", f"item={result['itemId']}"]
        if "wake" in result:
            fields.append(f"wake={result['wake']['outcome']}")
            if result["wake"].get("turnId"):
                fields.append(f"turn={result['wake']['turnId']}")
            reason = result["wake"].get("reason") or result["wake"].get("message")
            if reason:
                fields.append(f"reason={json.dumps(reason)}")
        if "loading" in result:
            fields.extend(format_loading_fields(result["loading"]))
        print("\t".join(fields))
    return 0 if result["outcome"] == "accepted" else 1


async def cmd_input(args: argparse.Namespace) -> int:
    message = message_text(args)
    async with AppServer(args.endpoint, args.timeout) as app:
        target = await resolve_thread_reference(app, args.thread_id, tree_thread_id=args.tree)
        if args.turn:
            result = await steer_turn(app, target, args.turn, message)
        else:
            result = await start_turn(app, target, message)
    result["messageRole"] = "user"
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['delivery']}\t{result['turnId']}\trole=user")
    return 0
