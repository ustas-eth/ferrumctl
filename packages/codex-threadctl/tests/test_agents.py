import unittest
from unittest import mock

from codex_threadctl import agents
from codex_threadctl.errors import ThreadctlError


def thread(
    thread_id,
    *,
    parent=None,
    path=None,
    depth=None,
    status="notLoaded",
    direct_input=None,
):
    source = "cli"
    if parent is not None:
        source = {
            "subAgent": {
                "thread_spawn": {
                    "parent_thread_id": parent,
                    "depth": depth,
                    "agent_path": path,
                    "agent_nickname": None,
                    "agent_role": None,
                }
            }
        }
    return {
        "id": thread_id,
        "parentThreadId": parent,
        "source": source,
        "status": {"type": status},
        "canAcceptDirectInput": direct_input,
    }


class AgentMetadataTests(unittest.TestCase):
    def test_extracts_structured_spawn_metadata(self):
        child = thread(
            "child",
            parent="root",
            path="/root/hunter",
            depth=1,
            direct_input=False,
        )

        self.assertEqual(agents.agent_path(child), "/root/hunter")
        self.assertEqual(agents.parent_thread_id(child), "root")
        self.assertEqual(agents.agent_depth(child), 1)
        self.assertEqual(agents.direct_input_owner(child), "parent")

    def test_falls_back_to_spawn_parent_and_preserves_pathless_v1(self):
        child = thread("child", parent="root", depth=1)
        child["parentThreadId"] = None

        self.assertEqual(agents.parent_thread_id(child), "root")
        self.assertIsNone(agents.agent_path(child))
        self.assertEqual(agents.direct_input_owner(child), "unknown")

    def test_agent_path_validation_is_canonical(self):
        for value in (
            "/root",
            "/root/hunter_2",
            "/root/hunter/reviewer3",
        ):
            with self.subTest(value=value):
                self.assertEqual(agents.validate_agent_path(value), value)
        for value in (
            "root/hunter",
            "/root/",
            "/root//reviewer",
            "/root/../x",
            "/root/Reviewer",
            "/root/re-viewer",
            "/root/root",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ThreadctlError, "agent path"):
                    agents.validate_agent_path(value)


class AgentResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_tree_from_any_member(self):
        root = thread("root", status="active", direct_input=True)
        worker = thread(
            "worker",
            parent="root",
            path="/root/worker",
            depth=1,
            status="active",
            direct_input=False,
        )
        reviewer = thread(
            "reviewer",
            parent="worker",
            path="/root/worker/reviewer",
            depth=2,
        )
        legacy = thread("legacy", parent="root", depth=1)
        by_id = {entry["id"]: entry for entry in (root, worker, reviewer, legacy)}

        with (
            mock.patch.object(
                agents,
                "read_thread",
                mock.AsyncMock(side_effect=lambda _app, thread_id: by_id[thread_id]),
            ),
            mock.patch.object(
                agents,
                "list_threads",
                mock.AsyncMock(return_value=[reviewer, legacy, worker]),
            ) as list_threads,
            mock.patch.object(
                agents,
                "list_loaded",
                mock.AsyncMock(return_value=["root", "worker"]),
            ),
        ):
            records = await agents.list_agent_tree(object(), "reviewer")

        self.assertEqual(
            [record["threadId"] for record in records],
            ["root", "legacy", "worker", "reviewer"],
        )
        self.assertEqual(records[0]["agentPath"], "/root")
        self.assertEqual(records[2]["inputOwner"], "parent")
        self.assertIsNone(records[1]["agentPath"])
        list_threads.assert_awaited_once_with(
            mock.ANY,
            ancestor_thread_id="root",
            limit=0,
            sort_key="created_at",
        )

    async def test_tree_keeps_anchor_lineage_missing_from_descendant_index(self):
        root = thread("root", direct_input=True)
        worker = thread(
            "worker",
            parent="root",
            path="/root/worker",
            depth=1,
            direct_input=False,
        )
        with (
            mock.patch.object(
                agents,
                "read_thread",
                mock.AsyncMock(
                    side_effect=lambda _app, thread_id: {
                        "root": root,
                        "worker": worker,
                    }[thread_id]
                ),
            ),
            mock.patch.object(
                agents,
                "list_threads",
                mock.AsyncMock(return_value=[]),
            ),
            mock.patch.object(
                agents,
                "list_loaded",
                mock.AsyncMock(return_value=[]),
            ),
        ):
            records = await agents.list_agent_tree(object(), "worker")

        self.assertEqual(
            [(record["agentPath"], record["threadId"]) for record in records],
            [("/root", "root"), ("/root/worker", "worker")],
        )

    async def test_scoped_resolution_uses_current_tree(self):
        records = [
            {"threadId": "root", "agentPath": "/root"},
            {"threadId": "worker", "agentPath": "/root/worker"},
        ]
        with (
            mock.patch.dict("os.environ", {"CODEX_THREAD_ID": "member"}),
            mock.patch.object(
                agents,
                "list_agent_tree",
                mock.AsyncMock(return_value=records),
            ) as list_tree,
        ):
            result = await agents.resolve_agent_path(object(), "/root/worker")

        self.assertEqual(result["threadId"], "worker")
        list_tree.assert_awaited_once_with(mock.ANY, "member")

    async def test_explicit_tree_overrides_current_identity(self):
        with (
            mock.patch.dict("os.environ", {"CODEX_THREAD_ID": "current"}),
            mock.patch.object(
                agents,
                "list_agent_tree",
                mock.AsyncMock(
                    return_value=[{"threadId": "worker", "agentPath": "/root/worker"}]
                ),
            ) as list_tree,
        ):
            result = await agents.resolve_agent_path(
                object(),
                "/root/worker",
                tree_thread_id="anchor",
            )

        self.assertEqual(result["threadId"], "worker")
        list_tree.assert_awaited_once_with(mock.ANY, "anchor")

    async def test_unscoped_resolution_requires_one_loaded_match(self):
        records = [
            {"threadId": "worker", "agentPath": "/root/worker"},
            {"threadId": "other", "agentPath": "/root/other"},
        ]
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(
                agents,
                "loaded_agent_records",
                mock.AsyncMock(return_value=records),
            ),
        ):
            result = await agents.resolve_agent_path(object(), "/root/worker")

        self.assertEqual(result["threadId"], "worker")

    async def test_duplicate_persisted_paths_are_ambiguous(self):
        records = [
            {"threadId": "old", "agentPath": "/root/worker"},
            {"threadId": "new", "agentPath": "/root/worker"},
        ]
        with mock.patch.object(
            agents,
            "list_agent_tree",
            mock.AsyncMock(return_value=records),
        ):
            with self.assertRaisesRegex(
                ThreadctlError,
                r"ambiguous.*old, new",
            ):
                await agents.resolve_agent_path(
                    object(),
                    "/root/worker",
                    tree_thread_id="root",
                )

    async def test_plain_thread_id_bypasses_resolution(self):
        with mock.patch.object(
            agents,
            "resolve_agent_path",
            mock.AsyncMock(),
        ) as resolve:
            result = await agents.resolve_thread_reference(object(), "thread-id")

        self.assertEqual(result, "thread-id")
        resolve.assert_not_awaited()
