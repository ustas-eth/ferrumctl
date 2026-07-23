import unittest
from unittest import mock

from codex_threadctl import turns
from codex_threadctl.errors import ThreadctlError
from codex_threadctl.history import MaterializedItem, MaterializedSelection


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
    async def test_recent_messages_projects_selected_materialized_items(self):
        selected_turn = turn(
            "turn",
            user("item-1", "request"),
            agent("item-2", "reply"),
        )
        selection = MaterializedSelection(
            [
                MaterializedItem(selected_turn, selected_turn["items"][0]),
                MaterializedItem(selected_turn, selected_turn["items"][1]),
            ],
            "thread/items/list",
        )
        selected = mock.AsyncMock(return_value=selection)
        with mock.patch.object(turns, "select_materialized_items", selected):
            result, backend = await turns.recent_messages(
                object(),
                "thread",
                turn_id="turn",
                after=("turn", "before"),
                before=("turn", "after"),
                limit=0,
            )

        self.assertEqual([entry["text"] for entry in result], ["request", "reply"])
        self.assertEqual(backend, "thread/items/list")
        selected.assert_awaited_once_with(
            mock.ANY,
            "thread",
            turn_id="turn",
            after=("turn", "before"),
            before=("turn", "after"),
            types={"userMessage", "agentMessage"},
            limit=0,
        )

    async def test_find_message_uses_turn_and_item_as_composite_locator(self):
        selected_turn = turn("old", agent("item-2", "wanted"))
        selection = MaterializedSelection(
            [MaterializedItem(selected_turn, selected_turn["items"][0])],
            "thread/turns/list",
        )
        selected = mock.AsyncMock(return_value=selection)
        with mock.patch.object(turns, "select_materialized_items", selected):
            result = await turns.find_message(object(), "thread", "old", "item-2")

        self.assertEqual(result["text"], "wanted")
        self.assertEqual(result["turnId"], "old")
        selected.assert_awaited_once_with(
            mock.ANY,
            "thread",
            turn_id="old",
            limit=0,
        )

    async def test_find_message_rejects_non_message_item(self):
        selected_turn = turn(
            "turn",
            {"id": "exec-1", "type": "commandExecution", "command": "true"},
        )
        selection = MaterializedSelection(
            [MaterializedItem(selected_turn, selected_turn["items"][0])],
            "thread/turns/list",
        )
        with mock.patch.object(
            turns,
            "select_materialized_items",
            mock.AsyncMock(return_value=selection),
        ):
            with self.assertRaisesRegex(ThreadctlError, "not a conversation message"):
                await turns.find_message(object(), "thread", "turn", "exec-1")

    async def test_find_message_reports_missing_item(self):
        selection = MaterializedSelection([], "thread/turns/list")
        with mock.patch.object(
            turns,
            "select_materialized_items",
            mock.AsyncMock(return_value=selection),
        ):
            with self.assertRaisesRegex(ThreadctlError, "message item not found"):
                await turns.find_message(object(), "thread", "turn", "missing")


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
