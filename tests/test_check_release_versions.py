from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import check_release_versions


class ReleaseVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.com")
        self.write_package("codex-test", "1.0.0")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "baseline")
        self.base = self.run_git("rev-parse", "HEAD").stdout.strip()

    def run_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def write_package(self, name: str, version: str) -> None:
        self.write_versions(name, version)
        self.write(f"packages/{name}/src/{name}.py", "VALUE = 1\n")

    def write_versions(self, name: str, version: str) -> None:
        self.write(
            f"packages/{name}/pyproject.toml",
            f'[project]\nname = "{name}"\nversion = "{version}"\n',
        )
        self.write(
            f"packages/{name}/plugins/{name}/.codex-plugin/plugin.json",
            f'{{"name":"{name}","version":"{version}"}}\n',
        )

    def errors(self) -> list[str]:
        _, errors = check_release_versions.version_report(self.root, self.base)
        return errors

    def test_runtime_change_requires_a_new_version(self) -> None:
        self.write("packages/codex-test/src/codex-test.py", "VALUE = 2\n")

        self.assertRegex(self.errors()[0], r"version remains 1\.0\.0")

        self.write_versions("codex-test", "1.0.1")
        self.assertEqual(self.errors(), [])

    def test_runtime_change_rejects_a_version_downgrade(self) -> None:
        self.write("packages/codex-test/src/codex-test.py", "VALUE = 2\n")
        self.write_versions("codex-test", "0.9.0")

        self.assertRegex(self.errors()[0], r"did not increase.*1\.0\.0.*0\.9\.0")

    def test_changed_package_rejects_nonstable_version_syntax(self) -> None:
        self.write("packages/codex-test/src/codex-test.py", "VALUE = 2\n")
        self.write_versions("codex-test", "1.0")

        with self.assertRaisesRegex(
            check_release_versions.ReleaseVersionError,
            r"MAJOR\.MINOR\.PATCH",
        ):
            check_release_versions.version_report(self.root, self.base)

    def test_plugin_only_change_requires_a_new_version(self) -> None:
        self.write(
            "packages/codex-test/plugins/codex-test/skills/test/SKILL.md",
            "updated\n",
        )

        self.assertRegex(self.errors()[0], r"version remains 1\.0\.0")

    def test_untracked_runtime_files_are_checked(self) -> None:
        self.write("packages/codex-test/src/new.py", "VALUE = 2\n")

        self.assertRegex(self.errors()[0], r"src/new\.py")

    def test_deleted_runtime_files_are_checked(self) -> None:
        (self.root / "packages/codex-test/src/codex-test.py").unlink()

        self.assertRegex(self.errors()[0], r"src/codex-test\.py")

    def test_renaming_runtime_file_out_of_release_inputs_is_checked(self) -> None:
        (self.root / "packages/codex-test/tests").mkdir()
        self.run_git(
            "mv",
            "packages/codex-test/src/codex-test.py",
            "packages/codex-test/tests/codex-test.py",
        )

        self.assertRegex(self.errors()[0], r"src/codex-test\.py")

    def test_tests_and_internal_docs_do_not_require_a_release(self) -> None:
        self.write("packages/codex-test/tests/test_tool.py", "pass\n")
        self.write("packages/codex-test/docs/design.md", "notes\n")

        changes, errors = check_release_versions.version_report(self.root, self.base)

        self.assertEqual(changes, [])
        self.assertEqual(errors, [])

    def test_new_package_does_not_need_a_previous_version(self) -> None:
        self.write_package("codex-new", "0.1.0")

        changes, errors = check_release_versions.version_report(self.root, self.base)

        self.assertIn(("codex-new", None, "0.1.0"), changes)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
