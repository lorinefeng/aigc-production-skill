#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_skill.py <skill-directory>")
        return 2
    skill_dir = Path(sys.argv[1])
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        print("SKILL.md not found")
        return 1
    content = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        print("invalid YAML frontmatter")
        return 1
    data = yaml.safe_load(match.group(1))
    if data.get("name") != skill_dir.name:
        print("frontmatter name must match skill directory")
        return 1
    if not str(data.get("description", "")).strip():
        print("description is required")
        return 1
    if "[TODO" in content:
        print("unfinished TODO found")
        return 1
    print("Skill is valid!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
