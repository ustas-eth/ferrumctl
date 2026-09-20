from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_local", ROOT / "scripts" / "update-local.py"
)
assert SPEC is not None and SPEC.loader is not None
update_local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_local)


class UpdateLocalTests(unittest.TestCase):
    def test_installs_current_packages_only(self) -> None:
        packages = sorted(
            path.parent.name for path in (ROOT / "packages").glob("*/pyproject.toml")
        )
        with patch.object(update_local, "run") as run:
            update_local.install_commands()
        self.assertCountEqual(
            run.call_args_list,
            [
                call(["uv", "tool", "install", "--reinstall", f"./packages/{name}"])
                for name in packages
            ],
        )

    def test_refresh_inventory_matches_marketplace(self) -> None:
        marketplace = json.loads(update_local.MARKETPLACE.read_text())
        versions = {}
        for plugin in marketplace["plugins"]:
            manifest = ROOT / plugin["source"]["path"] / ".codex-plugin/plugin.json"
            versions[plugin["name"]] = json.loads(manifest.read_text())["version"]
        self.assertEqual(update_local.expected_versions(), versions)


if __name__ == "__main__":
    unittest.main()
