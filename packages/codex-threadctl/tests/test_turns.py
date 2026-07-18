import unittest
from unittest import mock

from codex_threadctl import turns
from codex_threadctl.errors import ThreadctlError


def user(item_id, text):
    return {
        "id": item_id,
        "type": "userMessage",
        "content": [{"type": "text", "text": text}],
    }


def agent(item_id, text, phase="final_answer"):
    return {"id": item_id, "type": "agentMessage", "text": text, "phase": phase}


def turn(turn_id, *items, status="completed", started=100, completed=101):
    return {
        "id": turn_id,
        "status": status,
        "startedAt": started,
        "completedAt": completed,
        "itemsView": "summary",
        "items": list(items),
    }


class MessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_messages_pages_and_returns_chronological_tail(self):
        pages = [
            {
                "data": [turn("new", user("item-1", "new request"), agent("item-2", "new reply"))],
                "nextCursor": "older",
            },
            {
                "data": [turn("old", user("item-1", "old request"), agent("item-2", "old reply"))],
                "nextCursor": None,
            },
        ]
        with mock.patch.object(turns, "list_turn_page", mock.AsyncMock(side_effect=pages)):
            result = await turns.recent_messages(object(), "thread", limit=3)

        self.assertEqual([entry["text"] for entry in result], ["old reply", "new request", "new reply"])
        self.assertEqual(result[0]["turnId"], "old")
        self.assertEqual(result[1]["itemId"], "item-1")

    async def test_recent_messages_limit_one_returns_latest_response(self):
        page = {
            "data": [turn("new", user("item-1", "request"), agent("item-2", "reply"))],
            "nextCursor": "unused",
        }
        mocked = mock.AsyncMock(return_value=page)
        with mock.patch.object(turns, "list_turn_page", mocked):
            result = await turns.recent_messages(object(), "thread", limit=1)

        self.assertEqual([entry["text"] for entry in result], ["reply"])
        mocked.assert_awaited_once()

    async def test_find_message_uses_turn_and_item_as_composite_locator(self):
        pages = [
            {"data": [turn("new", agent("item-2", "wrong"))], "nextCursor": "older"},
            {"data": [turn("old", agent("item-2", "wanted"))], "nextCursor": None},
        ]
        mocked = mock.AsyncMock(side_effect=pages)
        with mock.patch.object(turns, "list_turn_page", mocked):
            result = await turns.find_message(object(), "thread", "old", "item-2")

        self.assertEqual(result["text"], "wanted")
        self.assertEqual(result["turnId"], "old")
        self.assertTrue(
            all(call.kwargs["items_view"] == "full" for call in mocked.await_args_list)
        )

    async def test_find_message_rejects_non_message_item(self):
        page = {
            "data": [
                turn(
                    "turn",
                    {"id": "exec-1", "type": "commandExecution", "command": "true"},
                )
            ],
            "nextCursor": None,
        }
        with mock.patch.object(turns, "list_turn_page", mock.AsyncMock(return_value=page)):
            with self.assertRaisesRegex(ThreadctlError, "not a conversation message"):
                await turns.find_message(object(), "thread", "turn", "exec-1")

    async def test_repeated_cursor_is_rejected(self):
        page = {"data": [turn("turn")], "nextCursor": "same"}
        with mock.patch.object(turns, "list_turn_page", mock.AsyncMock(return_value=page)):
            with self.assertRaisesRegex(ThreadctlError, "repeated"):
                await turns.recent_messages(object(), "thread", limit=0)


class InspectionTests(unittest.TestCase):
    def test_build_inspection_keeps_latest_full_and_summarizes_previous(self):
        latest = turn(
            "latest",
            user("item-1", "request"),
            {"id": "exec-1", "type": "commandExecution", "command": "true"},
            agent("item-2", "working"),
            status="inProgress",
            completed=None,
        )
        latest["itemsView"] = "full"
        previous = turn(
            "previous",
            user("item-3", "earlier request"),
            agent("item-4", "progress", phase="commentary"),
            {"id": "exec-2", "type": "commandExecution", "command": "true"},
            agent("item-5", "earlier reply"),
        )
        previous["itemsView"] = "full"
        result = turns.build_inspection(
            {"id": "thread", "status": {"type": "active"}, "cwd": "/work"},
            loaded=True,
            goal=None,
            goal_error=None,
            turns=[latest, previous],
            item_limit=0,
            context={"usedTokens": 10},
            compaction=None,
        )

        self.assertTrue(result["thread"]["loaded"])
        self.assertEqual(result["thread"]["cwd"], "/work")
        self.assertEqual(
            [item["type"] for item in result["latestTurn"]["items"]],
            ["userMessage", "commandExecution", "agentMessage"],
        )
        self.assertEqual(result["previousTurn"]["itemsView"], "summary")
        self.assertEqual(
            [item["text"] for item in result["previousTurn"]["items"]],
            ["earlier request", "earlier reply"],
        )
