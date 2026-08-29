import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from codex_memoryctl import cli, parser
from codex_memoryctl.cache import CachedArtifact, put_artifact


class CacheCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_info_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "derived.sqlite3"
            put_artifact(
                path,
                CachedArtifact(
                    key="key",
                    operation="summarize-v1",
                    text="retained work",
                    model="gpt-test",
                    effort="medium",
                    created_at="2026-01-02T03:04:05+00:00",
                    elapsed_seconds=1.0,
                    attempts=1,
                    usage={},
                    response_id=None,
                ),
                memory_ids=["sha256:a"],
                instructions="instructions",
                prompt="prompt",
            )

            info = parser.build_parser().parse_args(
                ["cache", "info", "--database", str(path), "--json"]
            )
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(await cli.dispatch(info), 0)
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["entryCount"], 1)
            self.assertEqual(parsed["operations"], {"summarize-v1": 1})

            clear = parser.build_parser().parse_args(
                ["cache", "clear", "--database", str(path), "--json"]
            )
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(await cli.dispatch(clear), 0)
            self.assertEqual(json.loads(output.getvalue())["clearedCount"], 1)

            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(await cli.dispatch(info), 0)
            self.assertEqual(json.loads(output.getvalue())["entryCount"], 0)


if __name__ == "__main__":
    unittest.main()
