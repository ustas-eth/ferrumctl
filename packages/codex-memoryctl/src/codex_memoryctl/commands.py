from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import websockets
from codex_threadctl.agents import is_agent_path, resolve_thread_reference
from codex_threadctl.appserver import (
    AppServer,
    list_loaded,
    read_thread,
    require_object,
)
from codex_threadctl.errors import AppServerResponseError, ThreadctlError

from .constants import CLIENT_VERSION
from .envelope import build_envelope, read_envelope, write_envelope
from .errors import InjectionUncertain, MemoryctlError
from .formatting import format_state
from .rollouts import MemoryState, load_rollout, resolve_codex_home, scan_rollout
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
            "memoryId": state.memory_id,
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


async def cmd_inject(args: argparse.Namespace) -> int:
    target_reference = current_thread_id(args.target, "target thread")

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
        provider = thread.get("modelProvider")
        if provider != "openai" and not args.allow_non_openai:
            shown = provider if isinstance(provider, str) and provider else "unknown"
            raise MemoryctlError(
                f"target model provider is {shown}; opaque compaction memory is "
                "OpenAI-specific (pass --allow-non-openai to test deliberately)"
            )

        if args.file is not None:
            if args.full_checkpoint:
                raise MemoryctlError(
                    "--full-checkpoint selects a rollout source and cannot be used with --file"
                )
            envelope = read_envelope(args.file)
            items = list(envelope["items"])
            memory_ids = [_export_memory_id(envelope)]
            scope = str(envelope["scope"])
            sources = [str(envelope.get("source", {}).get("threadId") or "file")]
        else:
            if args.full_checkpoint and len(args.state) != 1:
                raise MemoryctlError(
                    "--full-checkpoint requires exactly one --state"
                )
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

        target_path = thread.get("path")
        if isinstance(target_path, str) and Path(target_path).is_file():
            existing = {
                state.memory_id for state in scan_rollout(Path(target_path)).states
            }
            duplicates = sorted(existing.intersection(memory_ids))
            if duplicates and not args.allow_duplicate:
                raise MemoryctlError(
                    "target already contains memory "
                    + ", ".join(duplicates)
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
        except AppServerResponseError:
            raise
        except (OSError, ThreadctlError, websockets.WebSocketException) as exc:
            raise InjectionUncertain(target, memory_ids) from exc

    result: dict[str, Any] = {
        "outcome": "accepted",
        "targetThreadId": target,
        "scope": scope,
        "memoryIds": memory_ids,
        "sourceThreadIds": sources,
    }
    if args.purpose is not None:
        result["purpose"] = args.purpose
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        fields = [
            result["outcome"],
            target,
            f"scope={scope}",
            f"memories={','.join(memory_ids)}",
            f"sources={','.join(sources)}",
        ]
        if args.purpose is not None:
            fields.append(f"purpose={json.dumps(args.purpose)}")
        print("\t".join(fields))
    return 0
