from __future__ import annotations

import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from codex_wakectl import commands
from codex_wakectl import conditions
from codex_wakectl.conditions import new_job
from codex_wakectl.errors import WakeDeferred
from codex_wakectl.state import insert_job
from codex_wakectl.state import list_jobs


class FakeAppServer:
    def __init__(self, endpoint: str, timeout: float) -> None:
        self.endpoint = endpoint
        self.timeout = timeout

    async def __aenter__(self) -> "FakeAppServer":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def runner_args(state: Path) -> argparse.Namespace:
    return argparse.Namespace(
        state=state,
        lease_seconds=300,
        limit=None,
        endpoint="unix://",
        timeout=1.0,
        json=True,
    )


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeating_goal_job_rebases_then_fires_for_replacement(self) -> None:
        goal = {
            "status": "active",
            "tokensUsed": 5250,
            "createdAt": 20,
        }
        sent: list[tuple[str, str]] = []

        async def get_goal(app: object, thread_id: str):
            return dict(goal)

        async def send_turn(
            app: object,
            thread_id: str,
            message: str,
            *,
            allow_active: bool = False,
        ) -> dict[str, str]:
            sent.append((thread_id, message))
            return {"id": "wake-turn"}

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            job = new_job(
                {
                    "type": "goal",
                    "threadId": "worker",
                    "tokensUsedEvery": 1000,
                    "goalCreatedAt": 10,
                },
                "main",
                "milestone",
                "unix:///tmp/codex.sock",
            )
            job["lastTokensUsedBucket"] = 4
            insert_job(state, job)

            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                mock.patch.object(conditions, "get_goal", get_goal),
                mock.patch.object(commands, "send_turn", send_turn),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)
                pending = list_jobs(state, include_all=True)[0]
                self.assertEqual(pending["condition"]["goalCreatedAt"], 20)
                self.assertEqual(pending["lastTokensUsedBucket"], 5)
                self.assertEqual(pending["fireCount"], 0)

                goal["tokensUsed"] = 6100
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)

            pending = list_jobs(state, include_all=True)[0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["lastTokensUsedBucket"], 6)
            self.assertEqual(pending["fireCount"], 1)
            self.assertEqual(sent, [("main", "milestone")])

    async def test_stop_job_persists_turn_cursor_then_fires_on_completion(self) -> None:
        turns = [{"id": "turn-2", "status": "inProgress"}]
        sent: list[tuple[str, str]] = []

        async def list_turns(
            app: object,
            thread_id: str,
            *,
            limit: int = 1,
            items_view: str = "notLoaded",
        ) -> list[dict[str, str]]:
            return [dict(turn) for turn in turns[:limit]]

        async def send_turn(
            app: object,
            thread_id: str,
            message: str,
            *,
            allow_active: bool = False,
        ) -> dict[str, str]:
            sent.append((thread_id, message))
            return {"id": "turn-1"}

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            job = new_job(
                {
                    "type": "stop",
                    "threadId": "worker",
                    "cursorTurnId": "turn-1",
                    "cursorTurnStatus": "completed",
                },
                "main",
                "worker stopped",
                "unix:///tmp/codex.sock",
            )
            insert_job(state, job)

            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                mock.patch.object(conditions, "list_thread_turns", list_turns),
                mock.patch.object(commands, "send_turn", send_turn),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)
                pending = list_jobs(state, include_all=True)[0]
                self.assertEqual(pending["condition"]["cursorTurnId"], "turn-2")
                self.assertEqual(pending["condition"]["cursorTurnStatus"], "inProgress")

                turns[0]["status"] = "completed"
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)

            fired = list_jobs(state, include_all=True)[0]
            self.assertEqual(fired["status"], "fired")
            self.assertEqual(fired["fireCount"], 1)
            self.assertEqual(sent, [("main", "worker stopped")])

    async def test_deferred_delivery_stays_pending_without_runner_failure(self) -> None:
        async def ready(*args: object, **kwargs: object):
            return True, {}, "ready"

        async def defer(*args: object, **kwargs: object):
            raise WakeDeferred("thread is active")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            job = new_job(
                {"type": "time", "at": 1},
                "target",
                "message",
                "unix:///tmp/codex.sock",
            )
            insert_job(state, job)

            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                mock.patch.object(commands, "condition_ready", ready),
                mock.patch.object(commands, "send_turn", defer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)

            pending = list_jobs(state, include_all=True)[0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["lastReason"], "thread is active")
            self.assertNotIn("lastError", pending)

    async def test_operational_error_makes_runner_fail_and_remains_visible(self) -> None:
        class BrokenAppServer(FakeAppServer):
            async def __aenter__(self) -> "BrokenAppServer":
                raise OSError("socket unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            job = new_job(
                {
                    "type": "stop",
                    "threadId": "worker",
                    "cursorTurnId": None,
                    "cursorTurnStatus": None,
                },
                "main",
                "message",
                "unix:///tmp/codex.sock",
            )
            insert_job(state, job)

            with (
                mock.patch.object(commands, "AppServer", BrokenAppServer),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 1)

            pending = list_jobs(state, include_all=True)[0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(pending["lastError"], "socket unavailable")

    async def test_missing_turn_result_is_recorded_as_operational_error(self) -> None:
        async def ready(*args: object, **kwargs: object):
            return True, {}, "ready"

        async def missing_turn(*args: object, **kwargs: object):
            return None

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            insert_job(
                state,
                new_job(
                    {"type": "time", "at": 1},
                    "target",
                    "message",
                    "unix:///tmp/codex.sock",
                ),
            )
            with (
                mock.patch.object(commands, "AppServer", FakeAppServer),
                mock.patch.object(commands, "condition_ready", ready),
                mock.patch.object(commands, "send_turn", missing_turn),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 1)

            pending = list_jobs(state, include_all=True)[0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(
                pending["lastError"],
                "condition was ready but no input turn was created",
            )


if __name__ == "__main__":
    unittest.main()
