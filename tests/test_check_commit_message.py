from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_commit_message


class CommitMessageTests(unittest.TestCase):
    def assert_valid(self, message: str) -> None:
        self.assertEqual(check_commit_message.validate_message(message), [])

    def assert_invalid(self, message: str, expected: str) -> None:
        self.assertTrue(
            any(
                expected in error
                for error in check_commit_message.validate_message(message)
            )
        )

    def test_accepts_scoped_headers_and_optional_body(self) -> None:
        self.assert_valid("feat(threadctl): expose ordered activity")
        self.assert_valid(
            "fix(streamctl)!: change acknowledgement semantics\n\n"
            "BREAKING CHANGE: reader cursors now include authored entries.\n"
        )
        self.assert_valid("docs(repo): explain local development setup")
        self.assert_valid("feat(memoryctl): make compaction memory transferable")

    def test_accepts_git_generated_headers(self) -> None:
        for message in (
            "Merge branch 'main'",
            'Revert "feat(threadctl): expose ordered activity"',
            "fixup! feat(threadctl): expose ordered activity",
            "squash! fix(repo): enforce commit headers",
            "amend! docs(repo): explain local development setup",
        ):
            with self.subTest(message=message):
                self.assert_valid(message)

    def test_requires_known_type_and_scope(self) -> None:
        self.assert_invalid(
            "Add ordered activity",
            "header must use",
        )
        self.assert_invalid(
            "feat: expose ordered activity",
            "header must use",
        )
        self.assert_invalid(
            "change(threadctl): expose ordered activity",
            "unknown type",
        )
        self.assert_invalid(
            "feat(threads): expose ordered activity",
            "unknown scope",
        )

    def test_requires_a_concise_description(self) -> None:
        self.assert_invalid("fix(repo): short", "at least 8")
        self.assert_invalid(
            "fix(repo): enforce scoped commit messages.",
            "must not end with a period",
        )
        self.assert_invalid(
            "feat(threadctl): " + "x" * 60,
            "exceeds 72",
        )

    def test_cli_reports_actionable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "COMMIT_EDITMSG"
            path.write_text("fix: missing scope\n", encoding="utf-8")
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = check_commit_message.main([str(path)])

        self.assertEqual(result, 1)
        self.assertIn("type(scope): concise description", stderr.getvalue())
        self.assertIn("fix(threadctl)", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
