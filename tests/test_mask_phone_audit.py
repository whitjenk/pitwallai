"""No raw phone prefix logging — use mask_phone() everywhere."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {".git", ".venv", ".venv314", "__pycache__", "node_modules"}
_RAW_PHONE_LOG = re.compile(r"phone\[:6\]|phone\[:4\]|phone\[:8\]")


def test_no_raw_phone_prefix_in_logs() -> None:
    offenders: list[str] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.name == Path(__file__).name:
            # This audit file names the forbidden patterns in its regex.
            continue
        text = path.read_text(encoding="utf-8")
        if _RAW_PHONE_LOG.search(text):
            offenders.append(str(path.relative_to(_ROOT)))
    assert offenders == [], f"raw phone-prefix logging found: {offenders}"
