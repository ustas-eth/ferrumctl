import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamctl import state
from streamctl.errors import StreamctlError


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "streams.sqlite3"
        self.stream = state.create_stream(self.path, "review")

    def test_append_positions_are_monotonic_and_replies_stay_in_stream(self):
        first = state.append_entry(
            self.path,
            self.stream["streamId"],
            "a",
            "first",
        )
        second = state.append_entry(
            self.path,
            self.stream["streamId"],
            "b",
            "second",
            reply_to=first["position"],
        )

        self.assertEqual(first["position"], 1)
        self.assertEqual(second["position"], 2)
        self.assertEqual(second["replyTo"], 1)
        with self.assertRaisesRegex(StreamctlError, "reply position"):
            state.append_entry(
                self.path,
                self.stream["streamId"],
                "b",
                "invalid",
                reply_to=999,
            )
        self.assertEqual(
            state.list_entries(
                self.path,
                self.stream["streamId"],
                limit=0,
            )["tailPosition"],
            2,
        )

    def test_reader_cursor_lists_every_entry_after_ack(self):
        stream_id = self.stream["streamId"]
        state.append_entry(self.path, stream_id, "a", "one")
        state.append_entry(self.path, stream_id, "reader", "own message")
        state.append_entry(self.path, stream_id, "b", "three")

        state.acknowledge(self.path, stream_id, "reader", 1)
        unread = state.list_entries(
            self.path,
            stream_id,
            reader="reader",
            limit=0,
        )

        self.assertEqual(unread["ackThrough"], 1)
        self.assertEqual(
            [entry["position"] for entry in unread["entries"]],
            [2, 3],
        )

    def test_explicit_after_overrides_reader_cursor(self):
        stream_id = self.stream["streamId"]
        for index in range(1, 5):
            state.append_entry(self.path, stream_id, "a", str(index))
        state.acknowledge(self.path, stream_id, "reader", 3)

        result = state.list_entries(
            self.path,
            stream_id,
            reader="reader",
            after=1,
            limit=2,
        )

        self.assertEqual(result["ackThrough"], 3)
        self.assertEqual(result["after"], 1)
        self.assertEqual(result["lastPosition"], 3)
        self.assertEqual(result["tailPosition"], 4)
        self.assertEqual(
            [entry["position"] for entry in result["entries"]],
            [2, 3],
        )

    def test_ack_is_idempotent_monotonic_and_bounded_by_tail(self):
        stream_id = self.stream["streamId"]
        state.append_entry(self.path, stream_id, "a", "one")
        state.append_entry(self.path, stream_id, "a", "two")

        first = state.acknowledge(self.path, stream_id, "reader", 2)
        repeated = state.acknowledge(self.path, stream_id, "reader", 1)

        self.assertTrue(first["advanced"])
        self.assertFalse(repeated["advanced"])
        self.assertEqual(repeated["ackThrough"], 2)
        with self.assertRaisesRegex(StreamctlError, "beyond stream tail"):
            state.acknowledge(self.path, stream_id, "reader", 3)

    def test_missing_stream_is_an_error(self):
        with self.assertRaisesRegex(StreamctlError, "stream not found"):
            state.list_entries(self.path, "missing")

    def test_concurrent_appends_receive_unique_contiguous_positions(self):
        stream_id = self.stream["streamId"]

        def append(index):
            return state.append_entry(
                self.path,
                stream_id,
                f"writer-{index}",
                f"entry-{index}",
            )["position"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            positions = list(pool.map(append, range(12)))

        self.assertEqual(sorted(positions), list(range(1, 13)))
        entries = state.list_entries(self.path, stream_id, limit=0)["entries"]
        self.assertEqual([entry["position"] for entry in entries], list(range(1, 13)))

    def test_concurrent_acknowledgements_keep_the_highest_position(self):
        stream_id = self.stream["streamId"]
        for index in range(1, 21):
            state.append_entry(self.path, stream_id, "a", str(index))

        def acknowledge(through):
            return state.acknowledge(
                self.path,
                stream_id,
                "reader",
                through,
            )

        requested = [20, 3, 17, 1, 12, 8, 19, 4]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(acknowledge, requested))

        self.assertTrue(
            all(result["ackThrough"] >= result["requestedThrough"] for result in results)
        )
        final = state.list_entries(
            self.path,
            stream_id,
            reader="reader",
            limit=0,
        )
        self.assertEqual(final["ackThrough"], 20)
        self.assertEqual(final["entries"], [])

    def test_list_uses_one_snapshot_when_an_append_interleaves(self):
        stream_id = self.stream["streamId"]
        state.append_entry(self.path, stream_id, "a", "first")
        original_require_stream = state.require_stream

        def append_after_tail_read(conn, selected_stream_id):
            stream = original_require_stream(conn, selected_stream_id)
            writer = state.open_state(self.path)
            try:
                writer.execute("BEGIN IMMEDIATE")
                writer.execute(
                    """
                    INSERT INTO entries (
                        stream_id, position, author, body, reply_to, created_at
                    )
                    VALUES (?, 2, 'b', 'second', NULL, ?)
                    """,
                    (stream_id, state.now_seconds()),
                )
                writer.execute(
                    "UPDATE streams SET tail_position = 2 WHERE id = ?",
                    (stream_id,),
                )
                writer.commit()
            finally:
                writer.close()
            return stream

        with mock.patch.object(
            state,
            "require_stream",
            side_effect=append_after_tail_read,
        ):
            result = state.list_entries(self.path, stream_id, limit=0)

        self.assertEqual(result["tailPosition"], 1)
        self.assertEqual(result["lastPosition"], 1)
        self.assertEqual(
            [entry["position"] for entry in result["entries"]],
            [1],
        )
        self.assertEqual(
            state.list_entries(self.path, stream_id, limit=0)["tailPosition"],
            2,
        )

    def test_default_state_permissions_are_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "streamctl" / "streams.sqlite3"
            with mock.patch.object(state, "default_state_path", return_value=path):
                conn = state.open_state(path)
                conn.close()

            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_default_state_path_reuses_the_legacy_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "codex-streamctl" / "streams.sqlite3"
            legacy.parent.mkdir()
            legacy.touch()

            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": tmp}):
                self.assertEqual(state.default_state_path(), legacy)

    def test_default_state_path_prefers_the_current_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "codex-streamctl" / "streams.sqlite3"
            current = root / "streamctl" / "streams.sqlite3"
            legacy.parent.mkdir()
            legacy.touch()
            current.parent.mkdir()
            current.touch()

            with mock.patch.dict("os.environ", {"XDG_STATE_HOME": tmp}):
                self.assertEqual(state.default_state_path(), current)

    def test_existing_custom_state_permissions_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "shared"
            directory.mkdir(mode=0o755)
            path = directory / "streams.sqlite3"
            path.touch(mode=0o644)

            conn = state.open_state(path)
            conn.close()

            self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
