#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

EXCLUDED_PARTS = {".git", ".venv", "dist", "build", "smoke_artifacts", "__pycache__"}
FORBIDDEN_SUFFIXES = {".tif", ".tiff", ".psd", ".ai"}
TEXT_PATTERNS = {
    "absolute macOS user path": re.compile("/" + r"Users/[^/\s]+/"),
    "absolute Windows user path": re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\\s]+\\"),
    "embedded bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{12,}"),
    "embedded OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
}


def repository_files(root: Path) -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [
            path
            for path in root.rglob("*")
            if path.is_file() and not any(part in EXCLUDED_PARTS for part in path.parts)
        ]
    return [root / item.decode("utf-8") for item in output.split(b"\0") if item]


def scan(root: Path, deny_terms: list[str]) -> list[str]:
    findings: list[str] = []
    for path in repository_files(root):
        relative = path.relative_to(root)
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(f"forbidden production asset: {relative}")
        if path.name.startswith(".env") and path.name != ".env.example":
            findings.append(f"environment file must not be tracked: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in TEXT_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{label}: {relative}")
        lowered = text.casefold()
        for term in deny_terms:
            if term.strip() and term.casefold() in lowered:
                findings.append(f"private deny term found in {relative}")
    return sorted(set(findings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public repository content for private artifacts.")
    parser.add_argument("--deny-term", action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    findings = scan(root, args.deny_term)
    if findings:
        print("Privacy scan failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("Privacy scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
