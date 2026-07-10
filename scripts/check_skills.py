# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6,<7"]
# ///

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parent.parent


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def require_mapping(value: Any, path: Path, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{relative(path)}: {label} must be a mapping")
    return value


def read_skill_frontmatter(path: Path) -> dict[str, Any]:
    lines = path.read_text().splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{relative(path)}: missing opening frontmatter delimiter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError(f"{relative(path)}: missing closing frontmatter delimiter") from exc
    if not any(line.strip() for line in lines[end + 1 :]):
        raise ValueError(f"{relative(path)}: skill body is empty")
    return require_mapping(
        yaml.safe_load("\n".join(lines[1:end])),
        path,
        "frontmatter",
    )


def check_skill(path: Path) -> None:
    metadata = read_skill_frontmatter(path)
    expected_name = path.parent.name
    if metadata.get("name") != expected_name:
        raise ValueError(f"{relative(path)}: name must be {expected_name!r}")
    if not isinstance(metadata.get("description"), str) or not metadata["description"].strip():
        raise ValueError(f"{relative(path)}: description must be a nonempty string")

    agent_path = path.parent / "agents" / "openai.yaml"
    agent = require_mapping(yaml.safe_load(agent_path.read_text()), agent_path, "document")
    interface = require_mapping(agent.get("interface"), agent_path, "interface")
    for key in ("display_name", "short_description", "default_prompt"):
        if not isinstance(interface.get(key), str) or not interface[key].strip():
            raise ValueError(f"{relative(agent_path)}: {key} must be a nonempty string")
    policy = require_mapping(agent.get("policy"), agent_path, "policy")
    if not isinstance(policy.get("allow_implicit_invocation"), bool):
        raise ValueError(
            f"{relative(agent_path)}: allow_implicit_invocation must be a boolean"
        )


def check_manifest(path: Path) -> None:
    manifest = require_mapping(json.loads(path.read_text()), path, "document")
    expected_name = path.parent.parent.name
    if manifest.get("name") != expected_name:
        raise ValueError(f"{relative(path)}: name must be {expected_name!r}")
    for key in ("version", "description", "skills"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise ValueError(f"{relative(path)}: {key} must be a nonempty string")
    skills_path = (path.parent.parent / manifest["skills"]).resolve()
    if not skills_path.is_dir():
        raise ValueError(f"{relative(path)}: skills path does not exist")

    package_dir = path.parents[3]
    metadata_path = package_dir / "pyproject.toml"
    section = "project"
    if not metadata_path.exists():
        metadata_path = package_dir / "Cargo.toml"
        section = "package"
    metadata = tomllib.loads(metadata_path.read_text())
    package_version = require_mapping(metadata.get(section), metadata_path, section).get(
        "version"
    )
    if manifest["version"] != package_version:
        raise ValueError(
            f"{relative(path)}: version {manifest['version']!r} does not match "
            f"{relative(metadata_path)} {package_version!r}"
        )


def check_marketplace(manifests: list[Path]) -> None:
    path = ROOT / ".agents/plugins/marketplace.json"
    marketplace = require_mapping(json.loads(path.read_text()), path, "document")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise ValueError(f"{relative(path)}: plugins must be a list")

    expected = {manifest.parent.parent.name: manifest.parent.parent for manifest in manifests}
    actual: dict[str, Path] = {}
    for index, value in enumerate(plugins):
        plugin = require_mapping(value, path, f"plugins[{index}]")
        name = plugin.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{relative(path)}: plugins[{index}].name is invalid")
        if name in actual:
            raise ValueError(f"{relative(path)}: duplicate plugin {name!r}")
        source = require_mapping(plugin.get("source"), path, f"plugins[{index}].source")
        source_path = source.get("path")
        if source.get("source") != "local" or not isinstance(source_path, str):
            raise ValueError(f"{relative(path)}: plugin {name!r} must use a local path")
        resolved = (ROOT / source_path).resolve()
        if not (resolved / ".codex-plugin/plugin.json").is_file():
            raise ValueError(f"{relative(path)}: plugin path does not contain a manifest")
        actual[name] = resolved

    if set(actual) != set(expected):
        raise ValueError(
            f"{relative(path)}: marketplace plugins do not match package manifests"
        )
    for name, expected_path in expected.items():
        if actual[name] != expected_path.resolve():
            raise ValueError(f"{relative(path)}: plugin {name!r} points to the wrong path")


def main() -> None:
    skills = sorted(ROOT.glob("packages/*/plugins/*/skills/*/SKILL.md"))
    manifests = sorted(ROOT.glob("packages/*/plugins/*/.codex-plugin/plugin.json"))
    if not skills or not manifests:
        raise ValueError("no plugin skills or manifests found")
    for path in skills:
        check_skill(path)
    for path in manifests:
        check_manifest(path)
    check_marketplace(manifests)
    print(f"validated {len(skills)} skills and {len(manifests)} plugin manifests")


if __name__ == "__main__":
    main()
