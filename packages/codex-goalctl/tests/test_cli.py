from __future__ import annotations

import argparse
import contextlib
import io
import unittest

from codex_goalctl import cli


class ParseTests(unittest.TestCase):
    def test_timeout_must_be_positive(self) -> None:
        self.assertEqual(cli.positive_float("1.5"), 1.5)
        with self.assertRaises(argparse.ArgumentTypeError):
            cli.positive_float("0")

    def test_parser_rejects_negative_timeout(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.build_parser().parse_args(["--timeout", "-1", "get", "thread"])


if __name__ == "__main__":
    unittest.main()
