import io
import unittest
from contextlib import redirect_stdout

from codex_memoryctl import parser


class ParserTests(unittest.TestCase):
    def test_version(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-memoryctl 0.5.2\n")

    def test_parses_public_commands(self) -> None:
        cases = [
            ["cache", "info"],
            ["cache", "clear", "--json"],
            ["list"],
            ["list", "thread", "--origin", "standalone", "--limit", "0"],
            ["show", "thread@latest"],
            ["summarize", "thread@latest"],
            ["summarize", "thread@latest", "--focus", "network roots"],
            ["summarize", "thread@latest", "--no-cache"],
            ["diff", "thread@index:1", "thread@index:2"],
            ["index"],
            [
                "index",
                "thread",
                "--jobs",
                "2",
                "--refresh",
                "--from-index",
                "2",
                "--to-index",
                "20",
                "--since",
                "2026-01-01",
                "--until",
                "2026-01-31T23:59:59Z",
            ],
            ["search", "thread", "preset mismatch"],
            ["search", "thread", "preset.*mismatch", "--match", "regex"],
            ["export", "thread@window:2", "--output", "memory.json"],
            [
                "inject",
                "--self",
                "--state",
                "thread@latest",
                "--purpose",
                "recall an earlier decision",
            ],
            [
                "inject",
                "--to",
                "target",
                "--state",
                "first@latest",
                "--state",
                "second@latest",
            ],
            ["inject", "--to", "target", "--file", "memory.json"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertTrue(callable(parser.build_parser().parse_args(argv).func))

    def test_index_jobs_must_be_positive(self) -> None:
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(["index", "thread", "--jobs", "0"])

    def test_refresh_and_no_cache_are_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(
                ["summarize", "thread@latest", "--refresh", "--no-cache"]
            )

    def test_index_defaults_and_time_boundaries(self) -> None:
        args = parser.build_parser().parse_args(["index", "thread"])
        self.assertEqual(args.limit, 10)
        self.assertIsNone(args.since)

        args = parser.build_parser().parse_args(
            ["index", "thread", "--since", "2026-01-02"]
        )
        self.assertEqual(args.since.raw, "2026-01-02")
        self.assertTrue(args.since.date_only)

    def test_index_rejects_invalid_time_boundary(self) -> None:
        with self.assertRaises(SystemExit):
            parser.build_parser().parse_args(
                ["index", "thread", "--since", "2026-01-02T12:00:00"]
            )

    def test_inject_requires_one_source_form(self) -> None:
        for argv in (
            ["inject"],
            ["inject", "--self"],
            [
                "inject",
                "--self",
                "--state",
                "thread",
                "--file",
                "memory.json",
            ],
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    parser.build_parser().parse_args(argv)

    def test_inject_requires_one_target_mode(self) -> None:
        for argv in (
            ["inject", "--state", "thread"],
            [
                "inject",
                "--self",
                "--to",
                "target",
                "--state",
                "thread",
            ],
        ):
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit):
                    parser.build_parser().parse_args(argv)

    def test_global_options_work_after_command(self) -> None:
        args = parser.build_parser().parse_args(
            ["show", "thread@latest", "--codex-home", "/tmp/home", "--json"]
        )
        self.assertEqual(args.codex_home, "/tmp/home")
        self.assertTrue(args.json)
