from __future__ import annotations

import unittest
from unittest import mock

from codex_threadctl.errors import ThreadNotLoaded, ThreadStateError
from codex_wakectl import delivery
from codex_wakectl.errors import EventDeliveryUncertain


def event_job(**action: bool) -> dict[str, object]:
    return {
        "id": "job123",
        "condition": {"type": "goal", "threadId": "worker"},
        "targetThreadId": "target",
        "action": {"type": "event", **action},
        "fireCount": 0,
    }


class EventTextTests(unittest.TestCase):
    def test_event_text_is_short_and_identifies_the_condition(self) -> None:
        self.assertEqual(
            delivery.event_text(event_job(), "status is complete"),
            "Scheduled event job123/1: goal condition for worker matched: "
            "status is complete.",
        )

    def test_repeating_event_has_a_stable_sequence(self) -> None:
        job = event_job()
        job["fireCount"] = 2
        self.assertEqual(delivery.event_item_id(job), "amsg_wake_job123_3")


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_idle_event_injects_context_then_starts_empty_turn(self) -> None:
        notification = {"itemId": "amsg_wake_job123_1", "outcome": "accepted"}
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=["target"])),
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "idle"}),
            ),
            mock.patch.object(
                delivery,
                "notify_thread",
                mock.AsyncMock(return_value=notification),
            ) as notify,
            mock.patch.object(
                delivery,
                "wake_thread",
                mock.AsyncMock(
                    return_value={"outcome": "confirmedStarted", "turnId": "turn-1"}
                ),
            ) as wake,
        ):
            result = await delivery.deliver_event(object(), event_job(), "matched")

        self.assertEqual(result["delivery"], "eventStarted")
        self.assertEqual(result["turnId"], "turn-1")
        notify.assert_awaited_once_with(
            mock.ANY,
            "target",
            "wakectl",
            "Scheduled event job123/1: goal condition for worker matched: matched.",
            item_id="amsg_wake_job123_1",
        )
        wake.assert_awaited_once_with(mock.ANY, "target")

    async def test_active_event_waits_unless_notification_is_allowed(self) -> None:
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=["target"])),
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "active"}),
            ),
        ):
            with self.assertRaisesRegex(ThreadStateError, "notification was not allowed"):
                await delivery.deliver_event(object(), event_job(), "matched")

    async def test_active_notification_does_not_start_another_turn(self) -> None:
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=["target"])),
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "active"}),
            ),
            mock.patch.object(
                delivery,
                "notify_thread",
                mock.AsyncMock(
                    return_value={"itemId": "amsg_wake_job123_1", "outcome": "accepted"}
                ),
            ),
            mock.patch.object(
                delivery,
                "_active_turn_id",
                mock.AsyncMock(return_value="turn-active"),
            ),
            mock.patch.object(delivery, "wake_thread", mock.AsyncMock()) as wake,
        ):
            result = await delivery.deliver_event(
                object(), event_job(notifyActive=True), "matched"
            )

        self.assertEqual(result["delivery"], "notifiedActive")
        self.assertEqual(result["turnId"], "turn-active")
        wake.assert_not_awaited()

    async def test_unloaded_event_waits_without_explicit_resume(self) -> None:
        with mock.patch.object(
            delivery, "list_loaded", mock.AsyncMock(return_value=[])
        ):
            with self.assertRaises(ThreadNotLoaded):
                await delivery.deliver_event(object(), event_job(), "matched")

    async def test_resume_can_continue_goal_and_inject_event_into_active_turn(self) -> None:
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=[])),
            mock.patch.object(delivery, "resume_thread", mock.AsyncMock()) as resume,
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "active"}),
            ),
            mock.patch.object(
                delivery,
                "notify_thread",
                mock.AsyncMock(
                    return_value={"itemId": "amsg_wake_job123_1", "outcome": "accepted"}
                ),
            ),
            mock.patch.object(
                delivery,
                "_active_turn_id",
                mock.AsyncMock(return_value="goal-turn"),
            ),
        ):
            result = await delivery.deliver_event(
                object(), event_job(resume=True), "matched"
            )

        resume.assert_awaited_once_with(mock.ANY, "target", continue_goal=True)
        self.assertEqual(result["delivery"], "resumedActive")
        self.assertEqual(result["turnId"], "goal-turn")

    async def test_idle_race_into_active_work_counts_as_event_delivery(self) -> None:
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=["target"])),
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "idle"}),
            ),
            mock.patch.object(
                delivery,
                "notify_thread",
                mock.AsyncMock(
                    return_value={"itemId": "amsg_wake_job123_1", "outcome": "accepted"}
                ),
            ),
            mock.patch.object(
                delivery,
                "wake_thread",
                mock.AsyncMock(
                    return_value={
                        "outcome": "notSubmittedActive",
                        "turnId": "competing-turn",
                    }
                ),
            ),
        ):
            result = await delivery.deliver_event(object(), event_job(), "matched")

        self.assertEqual(result["delivery"], "eventNotifiedActive")
        self.assertEqual(result["turnId"], "competing-turn")

    async def test_uncertain_wake_does_not_hide_the_injected_event(self) -> None:
        with (
            mock.patch.object(delivery, "list_loaded", mock.AsyncMock(return_value=["target"])),
            mock.patch.object(
                delivery,
                "get_thread_status",
                mock.AsyncMock(return_value={"type": "idle"}),
            ),
            mock.patch.object(
                delivery,
                "notify_thread",
                mock.AsyncMock(
                    return_value={"itemId": "amsg_wake_job123_1", "outcome": "accepted"}
                ),
            ),
            mock.patch.object(
                delivery,
                "wake_thread",
                mock.AsyncMock(
                    return_value={
                        "outcome": "uncertain",
                        "turnId": "turn-1",
                        "reason": "confirmation timed out",
                    }
                ),
            ),
        ):
            with self.assertRaises(EventDeliveryUncertain) as raised:
                await delivery.deliver_event(object(), event_job(), "matched")

        self.assertEqual(raised.exception.item_id, "amsg_wake_job123_1")
        self.assertEqual(raised.exception.turn_id, "turn-1")

    async def test_input_action_uses_the_existing_confirmed_path(self) -> None:
        job = {
            "targetThreadId": "target",
            "action": {"type": "input", "message": "continue"},
        }
        with mock.patch.object(
            delivery,
            "deliver_input",
            mock.AsyncMock(return_value={"delivery": "started", "turnId": "turn-1"}),
        ) as send:
            result = await delivery.deliver_action(object(), job, "matched")

        self.assertEqual(result["delivery"], "started")
        send.assert_awaited_once_with(
            mock.ANY,
            "target",
            "continue",
            allow_active=False,
        )
