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
from codex_threadctl.errors import DeliveryUncertain, ThreadStateError
from codex_wakectl.conditions import new_job
from codex_wakectl.state import insert_job
from codex_wakectl.state import list_jobs


class FakeAppServer:
    def __init__(self, endpoint: str, timeout: float, **kwargs: object) -> None:
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
    async def test_goal_job_is_superseded_by_replacement(self) -> None:
        goal = {
            "status": "active",
            "tokensUsed": 5250,
            "createdAt": 20,
        }

        async def get_goal(app: object, thread_id: str):
            return dict(goal)

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
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 0)
            stored = list_jobs(state, include_all=True)[0]
            self.assertEqual(stored["status"], "superseded")
            self.assertEqual(stored["fireCount"], 0)

    async def test_stop_job_persists_turn_cursor_then_fires_on_completion(self) -> None:
        turns = [
            {"id": "turn-2", "status": "inProgress"},
            {"id": "turn-1", "status": "completed"},
        ]
        sent: list[tuple[str, str]] = []

        async def list_turn_page(
            app: object,
            thread_id: str,
            *,
            cursor: str | None = None,
            limit: int = 50,
            sort_direction: str = "desc",
            items_view: str = "notLoaded",
        ) -> dict[str, object]:
            return {"data": [dict(turn) for turn in turns], "nextCursor": None}

        async def deliver_input(
            app: object,
            thread_id: str,
            message: str,
            *,
            allow_active: bool = False,
        ) -> dict[str, str]:
            sent.append((thread_id, message))
            return {
                "turnId": "wake-turn",
                "clientMessageId": "client",
                "delivery": "started",
            }

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
                mock.patch.object(conditions, "list_turn_page", list_turn_page),
                mock.patch.object(commands, "deliver_input", deliver_input),
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
            self.assertEqual(fired["lastDeliveryMode"], "started")
            self.assertEqual(fired["lastClientMessageId"], "client")
            self.assertEqual(sent, [("main", "worker stopped")])

    async def test_deferred_delivery_stays_pending_without_runner_failure(self) -> None:
        async def ready(*args: object, **kwargs: object):
            return True, {}, "ready"

        async def defer(*args: object, **kwargs: object):
            raise ThreadStateError("thread is active")

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
                mock.patch.object(commands, "deliver_input", defer),
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

        async def missing_delivery(*args: object, **kwargs: object):
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
                mock.patch.object(commands, "deliver_input", missing_delivery),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 1)

            pending = list_jobs(state, include_all=True)[0]
            self.assertEqual(pending["status"], "pending")
            self.assertEqual(
                pending["lastError"],
                "condition was ready but input was not delivered",
            )

    async def test_uncertain_delivery_is_not_retried(self) -> None:
        async def ready(*args: object, **kwargs: object):
            return True, {}, "ready"

        async def uncertain(*args: object, **kwargs: object):
            raise DeliveryUncertain("submission", "client")

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
                mock.patch.object(commands, "deliver_input", uncertain),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(runner_args(state)), 1)

            stored = list_jobs(state, include_all=True)[0]
            self.assertEqual(stored["status"], "uncertain")
            self.assertEqual(stored["lastTurnId"], "submission")
            self.assertEqual(stored["lastClientMessageId"], "client")

    async def test_runner_rechecks_lease_before_delivery(self) -> None:
        async def ready(*args: object, **kwargs: object):
            return True, {}, "ready"

        delivery = mock.AsyncMock()
        args = runner_args(Path("unused"))
        args.lease_seconds = 1
        args.timeout = 2.0
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "jobs.sqlite3"
            args.state = state
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
                mock.patch.object(commands, "condition_ready", ready),
                mock.patch.object(
                    commands,
                    "renew_claimed_job",
                    side_effect=[True, False],
                ) as renew,
                mock.patch.object(commands, "deliver_input", delivery),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(await commands.cmd_run(args), 1)

        delivery.assert_not_awaited()
        self.assertEqual(renew.call_args_list[0].args[3], 25)


if __name__ == "__main__":
    unittest.main()
