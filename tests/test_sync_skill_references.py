from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "sync-skill-references.py"
)
SPEC = importlib.util.spec_from_file_location("sync_skill_references", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
sync_skill_references = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync_skill_references)


class SyncSkillReferencesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Path("docs/source.md")
        self.target = Path(
            "packages/codex-test/plugins/codex-test/"
            "skills/codex-test/references/current.md"
        )
        self.orphan = self.target.with_name("orphan.md")
        self.manual = self.target.with_name("manual.md")

        self.write(self.source, "# Source\n")
        self.write(
            Path("scripts/skill-references.json"),
            json.dumps(
                {
                    "references": [
                        {
                            "source": str(self.source),
                            "targets": [str(self.target)],
                        }
                    ]
                }
            ),
        )
        expected = sync_skill_references.generated_text(
            str(self.source),
            "# Source\n",
        )
        self.write(self.target, expected)
        self.write(
            self.orphan,
            sync_skill_references.generated_text(
                "docs/removed.md",
                "# Removed\n",
            ),
        )
        self.write(self.manual, "# Manual\n")

    def write(self, relative: Path, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def run_sync(self, *, check: bool) -> int:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return sync_skill_references.sync(check=check, root=self.root)

    def test_check_rejects_unmapped_generated_reference(self) -> None:
        self.assertEqual(self.run_sync(check=True), 1)

    def test_sync_removes_only_unmapped_generated_references(self) -> None:
        self.assertEqual(self.run_sync(check=False), 0)

        self.assertFalse((self.root / self.orphan).exists())
        self.assertTrue((self.root / self.target).exists())
        self.assertTrue((self.root / self.manual).exists())


if __name__ == "__main__":
    unittest.main()
