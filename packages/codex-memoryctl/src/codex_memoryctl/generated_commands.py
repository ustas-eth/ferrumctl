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
    rollout = load_rollout(resolve_codex_home(args.codex_home), reference.source)
    states = sorted(
        (state for state in rollout.states if state.origin == "checkpoint"),
        key=lambda state: state.checkpoint_index or 0,
    )
    if not states:
        raise MemoryctlError(f"thread has no portable memory checkpoints: {rollout.thread_id}")

    semaphore = asyncio.Semaphore(args.jobs)

    async def build(position: int) -> tuple[int, GenerationResult]:
        async with semaphore:
            if position == 0:
                result = await generated_text(
                    args,
                    operation="summarize-v1",
                    states=[states[position]],
                    prompt=summary_prompt(),
                )
            else:
                result = await generated_text(
                    args,
                    operation="diff-v1",
                    states=[states[position - 1], states[position]],
                    prompt=diff_prompt(),
                )
            return position, result

    built = await asyncio.gather(
        *(build(position) for position in range(len(states))),
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
            f"index generation failed for {len(failures)} of {len(states)} checkpoints; "
            f"completed entries were cached; first error: {failures[0]}"
        )
    results = {position: result for position, result in completed}
    records = []
    for position, state in enumerate(states):
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
        resolve_codex_home(args.codex_home),
        reference.source,
    )
    initial_checkpoints = [state.memory_id for state in states]
    current_checkpoints = [
        state.memory_id
        for state in refreshed.states
        if state.origin == "checkpoint"
    ]
    source_advanced = current_checkpoints != initial_checkpoints

    output = {
        "operation": "index",
        "threadId": rollout.thread_id,
        "rolloutPath": str(rollout.path),
        "database": str(Path(args.database).expanduser()),
        "model": args.model,
        "effort": args.effort,
        "checkpointCount": len(records),
        "generatedCount": sum(not result.cache_hit for result in results.values()),
        "cachedCount": sum(result.cache_hit for result in results.values()),
        "sourceAdvanced": source_advanced,
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
        if source_advanced:
            print(
                "codex-memoryctl: rollout advanced while the index was generated; "
                "rerun to include the new checkpoint",
                file=sys.stderr,
            )
    return 0
