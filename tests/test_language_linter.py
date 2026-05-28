"""Tests for tools/language_linter.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_language_linter_clean_on_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, str(root / "tools" / "language_linter.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
