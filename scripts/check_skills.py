# /// script
# requires-python = ">=3.11"
# dependencies = ["PyYAML>=6,<7"]
# ///

from __future__ import annotations

import json
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


def main() -> None:
    skills = sorted(ROOT.glob("packages/*/plugins/*/skills/*/SKILL.md"))
    manifests = sorted(ROOT.glob("packages/*/plugins/*/.codex-plugin/plugin.json"))
    if not skills or not manifests:
        raise ValueError("no plugin skills or manifests found")
    for path in skills:
        check_skill(path)
    for path in manifests:
        check_manifest(path)
    print(f"validated {len(skills)} skills and {len(manifests)} plugin manifests")


if __name__ == "__main__":
    main()
