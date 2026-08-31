from __future__ import annotations

import argparse
import copy
import json
import os
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import websockets
from codex_threadctl.agents import is_agent_path, resolve_thread_reference
from codex_threadctl.appserver import (
    AppServer,
    current_active_turn,
    is_parent_owned_input_error,
    list_loaded,
    list_thread_turns,
    read_thread,
    require_object,
)
from codex_threadctl.errors import AppServerResponseError, ThreadctlError

from .constants import CLIENT_VERSION
from .discovery import search_rollout
from .envelope import build_envelope, read_envelope, write_envelope
from .errors import InjectionUncertain, MemoryctlError
from .formatting import format_state
from .rollouts import (
    MemoryState,
    distinct_session_meta_thread_id,
    is_memory_item,
    load_rollout,
    memory_ref,
    resolve_codex_home,
    scan_rollout,
)
from .selectors import StateReference, parse_state_reference, select_state


def memoryctl_appserver(endpoint: str, timeout: float) -> AppServer:
    return AppServer(
        endpoint,
        timeout,
        client_name="codex_memoryctl",
        client_title="codex-memoryctl",
        client_version=CLIENT_VERSION,
    )


def current_thread_id(value: str | None, label: str) -> str:
    selected = value or os.environ.get("CODEX_THREAD_ID")
    if not selected:
        raise MemoryctlError(f"{label} is required when CODEX_THREAD_ID is unavailable")
    return selected


async def resolve_source(
    reference: StateReference,
    args: argparse.Namespace,
    app: AppServer | None = None,
) -> StateReference:
    if Path(reference.source).expanduser().is_file():
        return reference
    if not is_agent_path(reference.source):
        return reference
    if app is not None:
        thread_id = await resolve_thread_reference(
            app,
            reference.source,
            tree_thread_id=args.tree,
        )
    else:
        async with memoryctl_appserver(args.endpoint, args.timeout) as opened:
            thread_id = await resolve_thread_reference(
                opened,
                reference.source,
                tree_thread_id=args.tree,
            )
    return StateReference(thread_id, reference.selector)


async def load_state(
    value: str,
    args: argparse.Namespace,
    *,
    full_checkpoint: bool = False,
    app: AppServer | None = None,
) -> MemoryState:
    reference = await resolve_source(parse_state_reference(value), args, app)
    rollout = load_rollout(resolve_codex_home(args.codex_home), reference.source)
    return select_state(
        rollout,
        reference.selector,
        require_checkpoint=full_checkpoint,
    )


async def cmd_list(args: argparse.Namespace) -> int:
    source = current_thread_id(args.source, "source thread")
    reference = await resolve_source(StateReference(source, "latest"), args)
    rollout = load_rollout(resolve_codex_home(args.codex_home), reference.source)
    states = list(reversed(rollout.states))
    if args.origin != "all":
        states = [state for state in states if state.origin == args.origin]
    if args.limit:
        states = states[: args.limit]
    if args.json:
        print(
            json.dumps(
                {
                    "threadId": rollout.thread_id,
                    "sessionMetaThreadId": distinct_session_meta_thread_id(
                        rollout.thread_id,
                        rollout.session_meta_thread_id,
                    ),
                    "rolloutPath": str(rollout.path),
                    "states": [state.metadata() for state in states],
                },
                indent=2,
            )
        )
    else:
        for state in states:
            print(format_state(state))
    return 0


async def cmd_show(args: argparse.Namespace) -> int:
    state = await load_state(args.state, args)
    result = {
        **state.metadata(),
        "rolloutPath": str(state.rollout_path),
    }
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for key, value in result.items():
            if value is not None:
                print(f"{key}\t{value}")
    return 0


async def cmd_search(args: argparse.Namespace) -> int:
    source = current_thread_id(args.source, "source thread")
    reference = await resolve_source(StateReference(source, "latest"), args)
    rollout = load_rollout(
        resolve_codex_home(args.codex_home),
        reference.source,
        include_messages=True,
    )
    result = search_rollout(
        rollout,
        args.query,
        mode=args.match,
        limit=args.limit,
        context=args.context,
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    for candidate in result["candidates"]:
        checkpoint = candidate["checkpoint"]
        if checkpoint is None:
            fields = ["uncompacted"]
        else:
            fields = [
                "checkpoint",
                f"index={checkpoint['checkpointIndex']}",
                checkpoint["memoryId"],
            ]
            if checkpoint["windowNumber"] is not None:
                fields.append(f"window={checkpoint['windowNumber']}")
        fields.append(f"matches={candidate['matchCount']}")
        if candidate["closestLineDistance"] is not None:
            fields.append(f"distance={candidate['closestLineDistance']}")
        print("\t".join(fields))
        for message in candidate["messages"]:
            print(
                "\t".join(
                    (
                        "*" if message["matched"] else " ",
                        message["role"],
                        message["timestamp"] or "-",
                        message["text"],
                    )
                )
            )
    return 0


async def cmd_export(args: argparse.Namespace) -> int:
    state = await load_state(
        args.state,
        args,
        full_checkpoint=args.full_checkpoint,
    )
    envelope = build_envelope(state, full_checkpoint=args.full_checkpoint)
    write_envelope(envelope, args.output, force=args.force)
    if args.output != "-":
        result = {
            "outcome": "exported",
            "output": str(Path(args.output).expanduser()),
            "scope": envelope["scope"],
            "memoryId": memory_ref(state.memory_id),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(
                "\t".join(
                    (
                        result["outcome"],
                        result["output"],
                        result["scope"],
                        result["memoryId"],
                    )
                )
            )
    return 0


def _export_memory_id(envelope: dict[str, Any]) -> str:
    memory = envelope["memory"]
    return str(memory["id"])


def bind_to_current_turn(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rebound: list[dict[str, Any]] = []
    for source in items:
        if not is_memory_item(source):
            raise MemoryctlError("current-turn binding accepts memory-only transfers")
        item = copy.deepcopy(source)
        item["internal_chat_message_metadata_passthrough"] = {"turn_id": None}
        rebound.append(item)
    return rebound


def perspective_frame(
    target: str,
    event: str,
    **fields: Any,
) -> dict[str, Any]:
    payload = {"event": f"memoryctl.perspective.{event}", **fields}
    return {
        "type": "agent_message",
        "id": f"amsg_memoryctl_{uuid.uuid4().hex}",
        "author": "memoryctl",
        "recipient": target,
        "content": [
            {
                "type": "input_text",
                "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            }
        ],
    }


def frame_memory_batch(
    target: str,
    items: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    purpose: str | None,
) -> list[dict[str, Any]]:
    if not items or len(items) != len(sources):
        raise MemoryctlError("memory framing requires one source for each item")

    framed = [
        perspective_frame(
            target,
            "open",
            openedMemory=sources[0],
        )
    ]
    for index, item in enumerate(items):
        framed.append(item)
        if index + 1 < len(items):
            framed.append(
                perspective_frame(
                    target,
                    "transition",
                    closedMemory=sources[index],
                    openedMemory=sources[index + 1],
                )
            )

    closing: dict[str, Any] = {"closedMemory": sources[-1]}
    if purpose is not None:
        closing["callerPurpose"] = {
            "origin": "caller-supplied",
            "text": purpose,
        }
    framed.append(perspective_frame(target, "close", **closing))
    return framed


def repeated_memory_ids(memory_ids: list[str]) -> list[str]:
    counts = Counter(memory_ids)
    return sorted(value for value, count in counts.items() if count > 1)


async def target_has_materialized_turn(app: AppServer, target: str) -> bool:
    try:
        return bool(await list_thread_turns(app, target, limit=1))
    except AppServerResponseError as exc:
        payload = exc.payload
        message = payload.get("message") if isinstance(payload, dict) else None
        if (
            isinstance(payload, dict)
            and payload.get("code") == -32600
            and isinstance(message, str)
            and "thread/turns/list is unavailable before first user message" in message
        ):
            return False
        raise


async def cmd_inject(args: argparse.Namespace) -> int:
    self_target = bool(args.self_target)
    if self_target and args.purpose is None:
        raise MemoryctlError("--self requires --purpose")
    if self_target and args.binding not in (None, "current"):
        raise MemoryctlError(
            "--self uses current-turn binding; use --to for source binding"
        )
    if self_target and args.framing not in (None, "boundaries"):
        raise MemoryctlError(
            "--self uses perspective boundaries; use --to for unframed transfer"
        )
    if self_target and args.expect_no_turns:
        raise MemoryctlError("--expect-no-turns applies only to --to")
    if args.expect_no_turns and args.binding == "current":
        raise MemoryctlError(
            "--expect-no-turns cannot be combined with current-turn binding"
        )
    if args.framing == "none" and args.purpose is not None:
        raise MemoryctlError("--purpose requires --framing boundaries")
    if self_target and args.full_checkpoint:
        raise MemoryctlError(
            "--self accepts memory only; use --to with a fresh target when "
            "transferring a full checkpoint"
        )
    if args.full_checkpoint and args.binding == "current":
        raise MemoryctlError("full checkpoints preserve source turn binding")
    if args.full_checkpoint and args.framing == "boundaries":
        raise MemoryctlError("full checkpoints are unframed")
    if args.full_checkpoint and args.purpose is not None:
        raise MemoryctlError(
            "full checkpoints do not carry --purpose; give the target its task separately"
        )
    target_reference = current_thread_id(
        None if self_target else args.target,
        "target thread",
    )

    async with memoryctl_appserver(args.endpoint, args.timeout) as app:
        target = await resolve_thread_reference(
            app,
            target_reference,
            tree_thread_id=args.tree,
        )
        loaded = set(await list_loaded(app))
        if target not in loaded:
            raise MemoryctlError(
                f"target is not loaded on the selected app-server: {target}"
            )
        thread = await read_thread(app, target)
        status = thread.get("status")
        target_status = (
            str(status.get("type"))
            if isinstance(status, dict) and isinstance(status.get("type"), str)
            else "unknown"
        )
        provider = thread.get("modelProvider")
        if provider != "openai" and not args.allow_non_openai:
            shown = provider if isinstance(provider, str) and provider else "unknown"
            raise MemoryctlError(
                f"target model provider is {shown}; opaque compaction memory is "
                "OpenAI-specific (pass --allow-non-openai to override this check)"
            )
        if args.expect_no_turns:
            if await target_has_materialized_turn(app, target):
                raise MemoryctlError(
                    "target already has a materialized turn; "
                    "--expect-no-turns precondition failed"
                )

        if args.file is not None:
            if args.full_checkpoint:
                raise MemoryctlError(
                    "--full-checkpoint selects a rollout source and cannot be "
                    "used with --file"
                )
            envelope = read_envelope(args.file)
            items = list(envelope["items"])
            memory_ids = [_export_memory_id(envelope)]
            scope = str(envelope["scope"])
            claimed_thread_id = envelope.get("source", {}).get("threadId")
            sources = [
                claimed_thread_id
                if isinstance(claimed_thread_id, str) and claimed_thread_id
                else "file"
            ]
            source_basis = "export-metadata-claim"
            source_refs = [f"{sources[0]}@{memory_ref(memory_ids[0])}"]
        else:
            if args.full_checkpoint and len(args.state) != 1:
                raise MemoryctlError("--full-checkpoint requires exactly one --state")
            states = [
                await load_state(
                    value,
                    args,
                    full_checkpoint=args.full_checkpoint,
                    app=app,
                )
                for value in args.state
            ]
            if args.full_checkpoint:
                replacement = states[0].replacement_history
                if replacement is None:
                    raise MemoryctlError(
                        "full checkpoint source has no replacement history"
                    )
                items = list(replacement)
                scope = "checkpoint"
            else:
                items = [state.memory_item for state in states]
                scope = "memory"
            memory_ids = [state.memory_id for state in states]
            sources = [state.thread_id for state in states]
            source_basis = "local-rollout"
            source_refs = [
                f"{state.thread_id}@{memory_ref(state.memory_id)}" for state in states
            ]

        requested_duplicates = repeated_memory_ids(memory_ids)
        if requested_duplicates and not args.allow_duplicate:
            raise MemoryctlError(
                "requested batch repeats memory "
                + ", ".join(memory_ref(value) for value in requested_duplicates)
                + "; pass --allow-duplicate to repeat it deliberately"
            )

        source_memories = [
            {
                "position": position,
                "reference": reference,
                "sourceBasis": source_basis,
            }
            for position, (reference, memory_id) in enumerate(
                zip(source_refs, memory_ids, strict=True),
                1,
            )
        ]

        if scope != "memory":
            if self_target:
                raise MemoryctlError(
                    "--self accepts memory-only exports; use --to with a fresh "
                    "target for a full checkpoint"
                )
            if args.binding == "current":
                raise MemoryctlError("full checkpoints preserve source turn binding")
            if args.framing == "boundaries":
                raise MemoryctlError("full checkpoints are unframed")
            if args.purpose is not None:
                raise MemoryctlError(
                    "full checkpoints do not carry --purpose; "
                    "give the target its task separately"
                )

        turn_binding = args.binding or ("current" if self_target else "source")
        perspective_framing = args.framing or (
            "boundaries" if scope == "memory" else "none"
        )

        active_turn_id: str | None = None
        if turn_binding == "current":
            turn = await current_active_turn(app, target)
            active_turn_id = str(turn["id"])
            items = bind_to_current_turn(items)

        if perspective_framing == "boundaries":
            items = frame_memory_batch(target, items, source_memories, args.purpose)

        target_path = thread.get("path")
        if isinstance(target_path, str) and Path(target_path).is_file():
            existing = scan_rollout(Path(target_path)).visible_memory_ids
            duplicates = sorted(existing.intersection(memory_ids))
            if duplicates and not args.allow_duplicate:
                raise MemoryctlError(
                    "target already contains memory "
                    + ", ".join(memory_ref(value) for value in duplicates)
                    + "; pass --allow-duplicate to repeat it deliberately"
                )

        try:
            require_object(
                await app.request(
                    "thread/inject_items",
                    {"threadId": target, "items": items},
                ),
                "thread/inject_items result",
            )
        except AppServerResponseError as exc:
            if is_parent_owned_input_error(exc):
                raise MemoryctlError(
                    "thread is controlled by its native parent; external memory "
                    "injection is unavailable"
                ) from exc
            raise
        except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
            raise InjectionUncertain(
                target, [memory_ref(value) for value in memory_ids]
            ) from exc

    shown_memory_ids = [memory_ref(value) for value in memory_ids]
    if args.purpose is None:
        purpose_delivery = "none"
    else:
        purpose_delivery = "attributed-boundary"

    result: dict[str, Any] = {
        "outcome": "accepted",
        "targetThreadId": target,
        "scope": scope,
        "memoryIds": shown_memory_ids,
        "sourceThreadIds": sources,
        "sourceMemoryRefs": source_refs,
        "sourceBasis": source_basis,
        "sourceMemories": source_memories,
        "targetStatusBefore": target_status,
        "turnBinding": turn_binding,
        "perspectiveFraming": perspective_framing,
        "purposeDelivery": purpose_delivery,
        "expectNoTurns": bool(args.expect_no_turns),
    }
    if active_turn_id is not None:
        result["activeTurnId"] = active_turn_id
    if args.purpose is not None:
        result["purpose"] = args.purpose
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        fields = [
            result["outcome"],
            target,
            f"scope={scope}",
            f"memories={','.join(shown_memory_ids)}",
            f"sources={','.join(sources)}",
            f"source-basis={source_basis}",
            f"target-status-before={target_status}",
            (
                f"binding=current:{active_turn_id}"
                if active_turn_id is not None
                else "binding=source"
            ),
            f"framing={perspective_framing}",
            f"purpose-delivery={result['purposeDelivery']}",
        ]
        if args.expect_no_turns:
            fields.append("expect-no-turns=yes")
        if args.purpose is not None:
            fields.append(f"purpose={json.dumps(args.purpose)}")
        print("\t".join(fields))
    return 0
