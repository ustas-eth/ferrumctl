from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from .commands import current_thread_id, load_state, resolve_source
from .errors import MemoryctlError
from .generation import GenerationResult, diff_prompt, generate, summary_prompt
from .indexing import select_checkpoints, uncompacted_message_count
from .rollouts import MemoryState, load_rollout, memory_ref, resolve_codex_home
from .selectors import StateReference


def generation_metadata(result: GenerationResult) -> dict[str, Any]:
    artifact = result.artifact
    return {
        "cacheHit": result.cache_hit,
        "artifactKey": artifact.key,
        "model": artifact.model,
        "effort": artifact.effort,
        "createdAt": artifact.created_at,
        "elapsedSeconds": artifact.elapsed_seconds,
        "attempts": artifact.attempts,
        "usage": artifact.usage,
        "responseId": artifact.response_id,
    }


async def generated_text(
    args: argparse.Namespace,
    *,
    operation: str,
    states: list[MemoryState],
    prompt: str,
) -> GenerationResult:
    return await asyncio.to_thread(
        generate,
        Path(args.database),
        resolve_codex_home(args.codex_home),
        operation=operation,
        states=states,
        prompt=prompt,
        model=args.model,
        effort=args.effort,
        refresh=args.refresh,
    )


async def cmd_summarize(args: argparse.Namespace) -> int:
    state = await load_state(args.state, args)
    result = await generated_text(
        args,
        operation="summarize-v1",
        states=[state],
        prompt=summary_prompt(args.focus),
    )
    output = {
        "operation": "summarize",
        "state": state.metadata(),
        "text": result.artifact.text,
        "generation": generation_metadata(result),
        "database": str(Path(args.database).expanduser()),
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(result.artifact.text)
    return 0


async def cmd_diff(args: argparse.Namespace) -> int:
    older = await load_state(args.older, args)
    newer = await load_state(args.newer, args)
    result = await generated_text(
        args,
        operation="diff-v1",
        states=[older, newer],
        prompt=diff_prompt(args.focus),
    )
    output = {
        "operation": "diff",
        "older": older.metadata(),
        "newer": newer.metadata(),
        "text": result.artifact.text,
        "generation": generation_metadata(result),
        "database": str(Path(args.database).expanduser()),
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(result.artifact.text)
    return 0


async def cmd_index(args: argparse.Namespace) -> int:
    source = current_thread_id(args.source, "source thread")
    reference = await resolve_source(StateReference(source, "latest"), args)
    codex_home = resolve_codex_home(args.codex_home)
    rollout = load_rollout(
        codex_home,
        reference.source,
        include_messages=True,
    )
    selection = select_checkpoints(
        [state for state in rollout.states if state.origin == "checkpoint"],
        from_index=args.from_index,
        to_index=args.to_index,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )

    semaphore = asyncio.Semaphore(args.jobs)

    async def build(position: int) -> tuple[int, GenerationResult]:
        async with semaphore:
            if position == 0:
                result = await generated_text(
                    args,
                    operation="summarize-v1",
                    states=[selection.states[position]],
                    prompt=summary_prompt(),
                )
            else:
                result = await generated_text(
                    args,
                    operation="diff-v1",
                    states=[
                        selection.states[position - 1],
                        selection.states[position],
                    ],
                    prompt=diff_prompt(),
                )
            return position, result

    built = await asyncio.gather(
        *(build(position) for position in selection.selected_positions),
        return_exceptions=True,
    )
    failures: list[BaseException] = []
    completed: list[tuple[int, GenerationResult]] = []
    for value in built:
        if isinstance(value, BaseException):
            failures.append(value)
        else:
            completed.append(value)
    if failures:
        raise MemoryctlError(
            f"index generation failed for {len(failures)} of "
            f"{len(selection.selected_positions)} checkpoints; "
            f"completed entries were cached; first error: {failures[0]}"
        )
    results = {position: result for position, result in completed}
    records = []
    for position in selection.selected_positions:
        state = selection.states[position]
        result = results[position]
        records.append(
            {
                "position": state.checkpoint_index,
                "reference": f"{state.thread_id}@{memory_ref(state.memory_id)}",
                "observedAt": state.observed_at,
                "text": result.artifact.text,
                "cacheHit": result.cache_hit,
                "artifactKey": result.artifact.key,
            }
        )
    refreshed = load_rollout(
        codex_home,
        reference.source,
        include_messages=True,
    )
    initial_checkpoints = [state.memory_id for state in selection.states]
    refreshed_checkpoints = [
        state
        for state in refreshed.states
        if state.origin == "checkpoint"
    ]
    current_checkpoints = [state.memory_id for state in refreshed_checkpoints]
    source_advanced = current_checkpoints != initial_checkpoints
    tail_messages = uncompacted_message_count(refreshed)
    first_state = selection.selected_states[0]
    last_state = selection.selected_states[-1]
    first_index = first_state.checkpoint_index
    last_index = last_state.checkpoint_index
    assert first_index is not None
    assert last_index is not None

    output = {
        "operation": "index",
        "threadId": rollout.thread_id,
        "rolloutPath": str(rollout.path),
        "database": str(Path(args.database).expanduser()),
        "model": args.model,
        "effort": args.effort,
        "checkpointCount": len(selection.states),
        "matchingCheckpointCount": len(selection.matching_positions),
        "selectedCheckpointCount": len(selection.selected_positions),
        "generatedCount": sum(not result.cache_hit for result in results.values()),
        "cachedCount": sum(result.cache_hit for result in results.values()),
        "sourceAdvanced": source_advanced,
        "hasUncompactedTail": tail_messages > 0,
        "uncompactedMessageCount": tail_messages,
        "selection": {
            "limit": args.limit,
            "fromIndex": args.from_index,
            "toIndex": args.to_index,
            "since": args.since.raw if args.since is not None else None,
            "until": args.until.raw if args.until is not None else None,
            "firstIndex": first_index,
            "lastIndex": last_index,
            "firstObservedAt": first_state.observed_at,
            "lastObservedAt": last_state.observed_at,
            "hasEarlier": selection.selected_positions[0] > 0,
            "hasLater": selection.selected_positions[-1] < len(selection.states) - 1,
        },
        "records": records,
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        for record in records:
            print(
                f"[index:{record['position']} "
                f"{record['reference'].rsplit('@', 1)[-1]} "
                f"{record['observedAt'] or '-'}]"
            )
            print(record["text"])
            print()
        if len(selection.selected_positions) < len(selection.matching_positions):
            print(
                "codex-memoryctl: showing checkpoint indices "
                f"{first_index}-{last_index} "
                f"({len(selection.selected_positions)} of "
                f"{len(selection.matching_positions)} matching; "
                f"{len(selection.states)} total); use --to-index "
                f"{first_index - 1} with the same bounds for older checkpoints",
                file=sys.stderr,
            )
        if tail_messages:
            latest_checkpoint_index = refreshed_checkpoints[-1].checkpoint_index
            print(
                f"codex-memoryctl: {tail_messages} conversation message(s) follow "
                f"checkpoint {latest_checkpoint_index}; "
                "the index does not describe this uncompacted tail",
                file=sys.stderr,
            )
        if source_advanced:
            print(
                "codex-memoryctl: rollout advanced while the index was generated; "
                "rerun to include the new checkpoint",
                file=sys.stderr,
            )
    return 0
