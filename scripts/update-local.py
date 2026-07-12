#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets>=15,<16"]
# ///
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
PYTHON_PACKAGES = (
    "codex-goalctl",
    "codex-threadctl",
    "codex-wakectl",
)
PLUGIN_NAMES = (*PYTHON_PACKAGES, "codex-readcov")


def run(command: list[str]) -> None:
    print("+", shlex.join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def install_commands() -> None:
    for package in PYTHON_PACKAGES:
        run(["uv", "tool", "install", "--reinstall", f"./packages/{package}"])
    run(
        [
            "cargo",
            "install",
            "--locked",
            "--force",
            "--path",
            "./packages/codex-readcov",
        ]
    )


def expected_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for plugin in PLUGIN_NAMES:
        manifest = (
            ROOT
            / "packages"
            / plugin
            / "plugins"
            / plugin
            / ".codex-plugin"
            / "plugin.json"
        )
        data = json.loads(manifest.read_text())
        versions[plugin] = data["version"]
    return versions


async def refresh_plugins(endpoint: str) -> None:
    sys.path.insert(0, str(ROOT / "packages" / "codex-threadctl" / "src"))
    from codex_threadctl.appserver import AppServer, require_object
    from codex_threadctl.errors import ThreadctlError

    try:
        async with AppServer(
            endpoint,
            30,
            client_name="ferrumctl_maintenance",
            client_title="ferrumctl maintenance",
            client_version="1",
        ) as app:
            for plugin in PLUGIN_NAMES:
                await app.request(
                    "plugin/install",
                    {
                        "marketplacePath": str(MARKETPLACE),
                        "pluginName": plugin,
                    },
                )

            result = require_object(
                await app.request(
                    "skills/list",
                    {"cwds": [str(ROOT)], "forceReload": True},
                ),
                "skills/list result",
            )
    except ThreadctlError as exc:
        raise RuntimeError(str(exc)) from exc

    paths = {
        skill.get("name", ""): skill.get("path", "")
        for entry in result.get("data", [])
        for skill in entry.get("skills", [])
        if isinstance(skill, dict)
    }
    versions = expected_versions()
    for plugin, version in versions.items():
        name = f"{plugin}:{plugin}"
        path = paths.get(name, "")
        if f"/{plugin}/{version}/" not in path:
            raise RuntimeError(f"app-server did not load {plugin} {version}")
        print(f"{plugin} {version}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install ferrumctl from this checkout and refresh a running app-server"
    )
    parser.add_argument(
        "--endpoint",
        default="unix://",
        help="running app-server endpoint (default: unix://)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        install_commands()
        asyncio.run(refresh_plugins(args.endpoint))
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"update-local: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
