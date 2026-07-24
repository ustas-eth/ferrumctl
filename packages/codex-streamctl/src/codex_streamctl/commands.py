from __future__ import annotations

import argparse
import json
import os

from .errors import StreamctlError
from .state import acknowledge, append_entry, create_stream, list_entries


def current_identity(value: str | None, option: str) -> str:
    identity = value or os.environ.get("CODEX_THREAD_ID")
    if identity is None or not identity.strip():
        raise StreamctlError(
            f"{option} is required when CODEX_THREAD_ID is not set"
        )
    return identity


def cmd_create(args: argparse.Namespace) -> int:
    result = create_stream(args.state, args.label)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["streamId"])
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    author = current_identity(args.author, "--author")
    result = append_entry(
        args.state,
        args.stream_id,
        author,
        args.message,
        reply_to=args.reply_to,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["position"])
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    result = list_entries(
        args.state,
        args.stream_id,
        reader=args.reader,
        after=args.after,
        limit=args.limit,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for entry in result["entries"]:
            fields = [
                str(entry["position"]),
                json.dumps(entry["author"], ensure_ascii=False),
                json.dumps(entry["text"], ensure_ascii=False),
            ]
            if entry["replyTo"] is not None:
                fields.append(f"reply-to={entry['replyTo']}")
            print("\t".join(fields))
    return 0


def cmd_ack(args: argparse.Namespace) -> int:
    reader = current_identity(args.reader, "--reader")
    result = acknowledge(
        args.state,
        args.stream_id,
        reader,
        args.through,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            "\t".join(
                [
                    "ack",
                    result["streamId"],
                    f"reader={result['reader']}",
                    f"through={result['ackThrough']}",
                    f"advanced={str(result['advanced']).lower()}",
                ]
            )
        )
    return 0
