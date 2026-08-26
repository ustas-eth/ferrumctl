import io
import unittest
from contextlib import redirect_stdout

from codex_memoryctl import parser


class ParserTests(unittest.TestCase):
    def test_version(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-memoryctl 0.5.0\n")

    def test_parses_public_commands(self) -> None:
        cases = [
            ["list"],
            ["list", "thread", "--origin", "standalone", "--limit", "0"],
            ["show", "thread@latest"],
            ["summarize", "thread@latest"],
            ["summarize", "thread@latest", "--focus", "network roots"],
            ["diff", "thread@index:1", "thread@index:2"],
            ["index"],
            ["index", "thread", "--jobs", "2", "--refresh"],
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
