import unittest
from unittest import mock

from codex_threadctl import history, turns
from codex_threadctl.errors import AppServerResponseError, ThreadctlError


def item(item_id, kind="agentMessage"):
    return {"id": item_id, "type": kind, "text": item_id}


def turn(turn_id, *items):
    return {
        "id": turn_id,
        "status": "completed",
        "startedAt": 1,
        "completedAt": 2,
        "items": list(items),
    }


class HistorySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_tail_filters_before_applying_limit(self):
        pages = [
            {
                "data": [
                    turn(
                        "new",
                        item("command", "commandExecution"),
                        item("reply"),
                    )
                ],
                "nextCursor": "older",
            },
            {
                "data": [turn("old", item("request", "userMessage"))],
                "nextCursor": None,
            },
        ]
        listed = mock.AsyncMock(side_effect=pages)
        with mock.patch.object(history, "list_turn_page", listed):
            result = await history.select_materialized_items(
                object(),
                "thread",
                types={"userMessage", "agentMessage"},
                limit=2,
            )

        self.assertEqual(
            [entry.locator for entry in result.entries],
            [("old", "request"), ("new", "reply")],
        )
        self.assertEqual(result.backend, "thread/turns/list")
        self.assertEqual(listed.await_count, 2)

    async def test_filtered_items_and_messages_share_identity_and_order(self):
        page = {
            "data": [
                turn(
                    "turn",
                    item("request", "userMessage"),
                    item("command", "commandExecution"),
                    item("reply"),
                )
            ],
            "nextCursor": None,
        }
        with mock.patch.object(
            history,
            "list_turn_page",
            mock.AsyncMock(return_value=page),
        ):
            selected = await history.select_materialized_items(
                object(),
                "thread",
                types={"userMessage", "agentMessage"},
                limit=0,
            )
        with mock.patch.object(
            history,
            "list_turn_page",
            mock.AsyncMock(return_value=page),
        ):
            messages, _ = await turns.recent_messages(
                object(),
                "thread",
                limit=0,
            )

        self.assertEqual(
            [entry.locator for entry in selected.entries],
            [(message["turnId"], message["itemId"]) for message in messages],
        )

    async def test_after_returns_earliest_matches_and_before_is_exclusive(self):
        page = {
            "data": [
                turn("new", item("n1"), item("n2")),
                turn(
                    "old",
                    item("o1"),
                    item("ignored", "commandExecution"),
                    item("o2"),
                ),
            ],
            "nextCursor": None,
        }
        with mock.patch.object(
            history,
            "list_turn_page",
            mock.AsyncMock(return_value=page),
        ):
            result = await history.select_materialized_items(
                object(),
                "thread",
                after=("old", "o1"),
                before=("new", "n2"),
                types={"agentMessage"},
                limit=2,
            )

        self.assertEqual(
            [entry.locator for entry in result.entries],
            [("old", "o2"), ("new", "n1")],
        )

    async def test_after_range_stops_once_the_anchor_page_is_loaded(self):
        pages = [
            {
                "data": [turn("new", item("n1"))],
                "nextCursor": "older",
            },
            {
                "data": [turn("anchor", item("a1"))],
                "nextCursor": "unused",
            },
        ]
        listed = mock.AsyncMock(side_effect=pages)
        with mock.patch.object(history, "list_turn_page", listed):
            result = await history.select_materialized_items(
                object(),
                "thread",
                after=("anchor", "a1"),
                limit=1,
            )
        self.assertEqual([entry.locator for entry in result.entries], [("new", "n1")])
        self.assertEqual(listed.await_count, 2)

    async def test_before_without_after_returns_latest_matches(self):
        page = {
            "data": [
                turn("new", item("n1")),
                turn("old", item("o1"), item("o2")),
            ],
            "nextCursor": None,
        }
        with mock.patch.object(
            history,
            "list_turn_page",
            mock.AsyncMock(return_value=page),
        ):
            result = await history.select_materialized_items(
                object(),
                "thread",
                before=("new", "n1"),
                limit=1,
            )
        self.assertEqual([entry.locator for entry in result.entries], [("old", "o2")])

    async def test_unlimited_before_range_reads_all_older_pages(self):
        pages = [
            {
                "data": [turn("new", item("n1"), item("n2"))],
                "nextCursor": "older",
            },
            {
                "data": [turn("old", item("o1"), item("o2"))],
                "nextCursor": None,
            },
        ]
        listed = mock.AsyncMock(side_effect=pages)
        with mock.patch.object(history, "list_turn_page", listed):
            result = await history.select_materialized_items(
                object(),
                "thread",
                before=("new", "n2"),
                limit=0,
            )

        self.assertEqual(
            [entry.locator for entry in result.entries],
            [("old", "o1"), ("old", "o2"), ("new", "n1")],
        )
        self.assertEqual(listed.await_count, 2)

    async def test_missing_reversed_and_ambiguous_bounds_fail(self):
        base = history.turn_entries(turn("turn", item("a"), item("b")))
        with self.assertRaisesRegex(ThreadctlError, "after item not found"):
            history.range_entries(base, after=("turn", "missing"), before=None)
        with self.assertRaisesRegex(ThreadctlError, "must precede"):
            history.range_entries(
                base,
                after=("turn", "b"),
                before=("turn", "a"),
            )
        duplicate = [base[0], base[0]]
        with self.assertRaisesRegex(ThreadctlError, "ambiguous"):
            history.range_entries(duplicate, after=("turn", "a"), before=None)

    async def test_exact_turn_uses_native_item_pages(self):
        item_pages = [
            {"data": [item("one")], "nextCursor": "next"},
            {"data": [item("two")], "nextCursor": None},
        ]
        listed_items = mock.AsyncMock(side_effect=item_pages)
        listed_turns = mock.AsyncMock(
            return_value={"data": [turn("turn")], "nextCursor": None}
        )
        with (
            mock.patch.object(history, "list_item_page", listed_items),
            mock.patch.object(history, "list_turn_page", listed_turns),
        ):
            result = await history.select_materialized_items(
                object(),
                "thread",
                turn_id="turn",
                limit=0,
            )

        self.assertEqual(result.backend, "thread/items/list")
        self.assertEqual(
            [entry.locator for entry in result.entries],
            [("turn", "one"), ("turn", "two")],
        )

    async def test_exact_turn_accepts_turn_wrapped_native_items(self):
        listed_items = mock.AsyncMock(
            return_value={
                "data": [{"turnId": "turn", "item": item("one")}],
                "nextCursor": None,
            }
        )
        listed_turns = mock.AsyncMock(
            return_value={"data": [turn("turn")], "nextCursor": None}
        )
        with (
            mock.patch.object(history, "list_item_page", listed_items),
            mock.patch.object(history, "list_turn_page", listed_turns),
        ):
            result = await history.select_materialized_items(
                object(),
                "thread",
                turn_id="turn",
                limit=0,
            )

        self.assertEqual(result.entries[0].locator, ("turn", "one"))

    async def test_exact_turn_rejects_mismatched_native_item_turn(self):
        listed_items = mock.AsyncMock(
            return_value={
                "data": [{"turnId": "other", "item": item("one")}],
                "nextCursor": None,
            }
        )
        with mock.patch.object(history, "list_item_page", listed_items):
            with self.assertRaisesRegex(ThreadctlError, "unexpected turn"):
                await history.select_materialized_items(
                    object(),
                    "thread",
                    turn_id="turn",
                    limit=0,
                )

    async def test_exact_turn_falls_back_only_when_native_is_unsupported(self):
        unsupported = AppServerResponseError(
            {"code": -32601, "message": "thread/items/list is not supported yet"}
        )
        listed_turns = mock.AsyncMock(
            return_value={
                "data": [turn("turn", item("one"))],
                "nextCursor": None,
            }
        )
        with (
            mock.patch.object(
                history,
                "list_item_page",
                mock.AsyncMock(side_effect=unsupported),
            ),
            mock.patch.object(history, "list_turn_page", listed_turns),
        ):
            result = await history.select_materialized_items(
                object(),
                "thread",
                turn_id="turn",
                limit=0,
            )
        self.assertEqual(result.backend, "thread/turns/list")
        self.assertEqual(result.entries[0].locator, ("turn", "one"))
        self.assertEqual(listed_turns.await_args.kwargs["items_view"], "full")

    async def test_native_operational_error_is_not_hidden(self):
        error = AppServerResponseError({"code": -32000, "message": "database failed"})
        with mock.patch.object(
            history,
            "list_item_page",
            mock.AsyncMock(side_effect=error),
        ):
            with self.assertRaisesRegex(AppServerResponseError, "database failed"):
                await history.select_materialized_items(
                    object(),
                    "thread",
                    turn_id="turn",
                    limit=0,
                )

    async def test_repeated_turn_and_item_cursors_are_rejected(self):
        repeated_turn = {"data": [turn("turn")], "nextCursor": "same"}
        with mock.patch.object(
            history,
            "list_turn_page",
            mock.AsyncMock(return_value=repeated_turn),
        ):
            with self.assertRaisesRegex(ThreadctlError, "turn pagination cursor"):
                await history.select_materialized_items(
                    object(),
                    "thread",
                    limit=0,
                )

        repeated_item = {"data": [item("item")], "nextCursor": "same"}
        with mock.patch.object(
            history,
            "list_item_page",
            mock.AsyncMock(return_value=repeated_item),
        ):
            with self.assertRaisesRegex(ThreadctlError, "item pagination cursor"):
                await history.select_materialized_items(
                    object(),
                    "thread",
                    turn_id="turn",
                    limit=0,
                )

    async def test_empty_turn_page_with_cursor_does_not_end_scan(self):
        pages = [
            {"data": [], "nextCursor": "next"},
            {"data": [turn("turn", item("item"))], "nextCursor": None},
        ]
        listed = mock.AsyncMock(side_effect=pages)
        with mock.patch.object(history, "list_turn_page", listed):
            result = await history.select_materialized_items(
                object(),
                "thread",
                limit=0,
            )

        self.assertEqual(result.entries[0].locator, ("turn", "item"))
        self.assertEqual(listed.await_count, 2)
