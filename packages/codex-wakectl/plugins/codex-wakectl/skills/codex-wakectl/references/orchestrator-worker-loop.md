<!-- Generated from docs/workflows/orchestrator-worker-loop.md. Do not edit directly. Run `python3 scripts/sync-skill-references.py`. -->

# Orchestrator Worker Loop

This workflow is for a Codex main thread that supervises other Codex threads or
subagents with the ferrumctl tools.

## Shape

1. Start a shared app-server and connect the sessions that need host control:

```sh
codex app-server --listen unix://
codex --remote unix://
```

2. Identify the worker and orchestrator thread ids. For v1 Codex subagents, the
   subagent `agent_id` is the thread id.

3. For read coverage, snapshot before the worker starts substantial work:

```sh
codex-readcov snapshot "$WORKER" > before.json
```

4. For durable work, assign a fresh goal:

```sh
codex-goalctl replace "$WORKER" "Review this code and mark the goal complete."
```

5. Schedule a wake back to the orchestrator before the worker can finish:

```sh
codex-wakectl add goal "$WORKER" \
  --status complete,blocked,budgetLimited,usageLimited \
  --to "$ORCH" \
  "Worker goal stopped. Inspect it."
```

For workers without goals, watch the turn stop instead:

```sh
codex-wakectl add stop "$WORKER" --to "$ORCH" "Worker stopped. Inspect it."
```

6. Wake the worker when it should act now:

```sh
codex-wakectl send "$WORKER" "A goal was assigned. Call get_goal and proceed."
```

7. Inspect the read delta after the worker runs:

```sh
codex-readcov delta before.json PATH --limit 20
```

## Operating Rules

- Treat wakes as polling-backed notifications, not exact events.
- Keep wake messages idempotent; they may arrive late or after manual handling.
- Cancel stale wake jobs when the orchestrator already handled the worker result.
- Create `stop` watches before the turn they should observe can finish.
- Avoid `--allow-active` unless overlapping turns are intentional.
- Use `codex-readcov` as transcript coverage, not as an OS audit log.
- Keep CLI commands neutral; put opinionated supervision behavior in skills or
  orchestrator prompts.
