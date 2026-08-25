import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from codex_memoryctl import commands, parser
from codex_memoryctl.discovery import search_rollout
from codex_memoryctl.errors import MemoryctlError
from codex_memoryctl.rollouts import scan_rollout

THREAD_ID = "01a00000-0000-7000-8000-000000000010"


def message(role: str, text: str) -> dict:
    return {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": role,
            "content": [{"type": "input_text", "text": text}],
        },
    }


def checkpoint(name: str) -> dict:
    return {
        "type": "compacted",
        "payload": {
            "replacement_history": [
                {
                    "type": "compaction",
                    "id": f"cmp_{name}",
                    "encrypted_content": name,
                }
            ]
        },
    }


def rollout(records: list[dict]):
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / f"rollout-{THREAD_ID}.jsonl"
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    return directory, scan_rollout(path, include_messages=True)


class DiscoveryTests(unittest.TestCase):
    def test_token_search_matches_across_one_checkpoint_segment(self) -> None:
        directory, value = rollout(
            [
                message("user", "Use the release preset."),
                message("assistant", "The runner has a version mismatch."),
                checkpoint("first"),
            ]
        )
        self.addCleanup(directory.cleanup)

        result = search_rollout(
            value,
            "preset mismatch",
            mode="tokens",
            limit=20,
            context=0,
        )

        self.assertEqual(result["candidateCount"], 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["checkpoint"]["checkpointIndex"], 1)
        self.assertEqual(candidate["matchCount"], 2)
        self.assertEqual(
            [entry["text"] for entry in candidate["messages"]],
            ["Use the release preset.", "The runner has a version mismatch."],
        )

    def test_phrase_and_regex_modes_match_individual_messages(self) -> None:
        directory, value = rollout(
            [message("assistant", "Preset runner mismatch."), checkpoint("first")]
        )
        self.addCleanup(directory.cleanup)

        phrase = search_rollout(
            value,
            "runner mismatch",
            mode="phrase",
            limit=20,
            context=0,
        )
        regex = search_rollout(
            value,
            r"preset\s+runner",
            mode="regex",
            limit=20,
            context=0,
        )

        self.assertEqual(phrase["candidateCount"], 1)
        self.assertEqual(regex["candidateCount"], 1)

    def test_uncompacted_match_is_reported_without_a_checkpoint(self) -> None:
        directory, value = rollout(
            [checkpoint("first"), message("user", "exact current evidence")]
        )
        self.addCleanup(directory.cleanup)

        result = search_rollout(
            value,
            "current evidence",
            mode="tokens",
            limit=20,
            context=1,
        )

        self.assertIsNone(result["candidates"][0]["checkpoint"])
        self.assertIsNone(result["candidates"][0]["closestLineDistance"])

    def test_invalid_regex_fails_cleanly(self) -> None:
        directory, value = rollout([message("user", "text"), checkpoint("first")])
        self.addCleanup(directory.cleanup)
        with self.assertRaisesRegex(MemoryctlError, "regular expression"):
            search_rollout(
                value,
                "[",
                mode="regex",
                limit=20,
                context=0,
            )

    def test_limit_zero_returns_all_candidates(self) -> None:
        directory, value = rollout(
            [
                message("user", "needle one"),
                checkpoint("first"),
                message("assistant", "needle two"),
                checkpoint("second"),
            ]
        )
        self.addCleanup(directory.cleanup)

        limited = search_rollout(
            value,
            "needle",
            mode="tokens",
            limit=1,
            context=0,
        )
        complete = search_rollout(
            value,
            "needle",
            mode="tokens",
            limit=0,
            context=0,
        )

        self.assertEqual(len(limited["candidates"]), 1)
        self.assertEqual(len(complete["candidates"]), 2)


class SearchCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_command_reports_canonical_source_and_uncompacted_tail(
        self,
    ) -> None:
        directory, value = rollout(
            [checkpoint("first"), message("assistant", "recent needle")]
        )
        self.addCleanup(directory.cleanup)
        args = parser.build_parser().parse_args(
            ["search", str(value.path), "recent needle", "--json"]
        )
        with redirect_stdout(io.StringIO()) as output:
            result = await commands.cmd_search(args)
        document = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(document["threadId"], THREAD_ID)
        self.assertIsNone(document["candidates"][0]["checkpoint"])


if __name__ == "__main__":
    unittest.main()
