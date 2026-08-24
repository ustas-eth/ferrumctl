import io
import unittest
from contextlib import redirect_stdout

from codex_memoryctl import parser


class ParserTests(unittest.TestCase):
    def test_version(self) -> None:
        with redirect_stdout(io.StringIO()) as output:
            with self.assertRaisesRegex(SystemExit, "0"):
                parser.build_parser().parse_args(["--version"])
        self.assertEqual(output.getvalue(), "codex-memoryctl 0.2.0\n")

    def test_parses_public_commands(self) -> None:
        cases = [
            ["list"],
            ["list", "thread", "--origin", "standalone", "--limit", "0"],
            ["show", "thread@latest"],
            ["export", "thread@window:2", "--output", "memory.json"],
            ["inject", "--state", "thread@latest"],
            [
                "inject",
                "target",
                "--state",
                "first@latest",
                "--state",
                "second@latest",
            ],
            ["inject", "--file", "memory.json"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertTrue(callable(parser.build_parser().parse_args(argv).func))

    def test_inject_requires_one_source_form(self) -> None:
        for argv in (
            ["inject"],
            ["inject", "--state", "thread", "--file", "memory.json"],
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
