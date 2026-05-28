#!/usr/bin/env python3
"""CI linter: flag directive language in user-facing agent/WhatsApp copy."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("whatsapp", "intelligence", "agents", "orchestrator")
EXCLUDE_DIR_NAMES = {"tests", "tools", "data", "__pycache__"}
EXCLUDE_FILE_PREFIXES = ("test_",)
EXCLUDE_FILE_SUFFIXES = ("_test.py",)

DIRECTIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("box now", re.compile(r"\bbox now\b", re.IGNORECASE)),
    ("pit now", re.compile(r"\bpit now\b", re.IGNORECASE)),
    ("transfer in/out now", re.compile(r"\btransfer (in|out) now\b", re.IGNORECASE)),
    ("you must/should/need to", re.compile(r"\byou (must|should|need to)\b", re.IGNORECASE)),
    ("use your chip", re.compile(r"\buse your (chip|wildcard|limitless)\b", re.IGNORECASE)),
    ("do not hold/keep/pick", re.compile(r"\bdo not (hold|keep|pick)\b", re.IGNORECASE)),
    ("immediately transfer", re.compile(r"\bimmediately (transfer|swap|change)\b", re.IGNORECASE)),
    ("guaranteed/certain", re.compile(r"\b(guaranteed|certain|will definitely)\b", re.IGNORECASE)),
    ("buy now", re.compile(r"\bbuy now\b", re.IGNORECASE)),
    ("sell now", re.compile(r"\bsell now\b", re.IGNORECASE)),
]


def _should_scan(path: Path) -> bool:
    if path.suffix != ".py":
        return False
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return False
    name = path.name
    if name.startswith(EXCLUDE_FILE_PREFIXES):
        return False
    if name.endswith(EXCLUDE_FILE_SUFFIXES):
        return False
    return True


def _scan_file(path: Path) -> list[tuple[int, str, str]]:
    violations: list[tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return violations
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for label, pattern in DIRECTIVE_PATTERNS:
            match = pattern.search(line)
            if match:
                violations.append((line_no, match.group(0), label))
    return violations


def main() -> int:
    all_violations: list[tuple[Path, int, str, str]] = []
    for dir_name in SCAN_DIRS:
        base = ROOT / dir_name
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if not _should_scan(path):
                continue
            for line_no, matched, label in _scan_file(path):
                all_violations.append((path.relative_to(ROOT), line_no, matched, label))

    if not all_violations:
        print("No directive language violations found.")
        return 0

    print("DIRECTIVE LANGUAGE FOUND:")
    for path, line_no, matched, label in all_violations:
        rel = path.as_posix()
        print(f'[{rel}:{line_no}] "{matched}"')
        print(f"Pattern: {label}")
        print("---")
    print(f"{len(all_violations)} violations found.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
