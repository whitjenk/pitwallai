"""core/ stays pure: no dependency on the DB, chat platforms or the old agents.

Fails if any file in ``core/`` has a *top-level* import of a forbidden module.
This is the structural guarantee behind briefs 002/004 — the fantasy brain must
be reachable without dragging in SQLAlchemy, Slack/WhatsApp or the agent layer.

Lazy imports inside a function body are allowed (e.g. the price catalog's
optional DB overlay, only ever called by the legacy db layer): they keep
``import core.*`` clean while leaving a seam for the legacy app. Adding a plain
``import db`` (or any forbidden module) to the top of a core file fails this test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[1] / "core"

# A core file may not import any of these (by exact name or as a dotted prefix).
FORBIDDEN = (
    "db",
    "whatsapp",
    "slack_app",
    "store",
    "agents",
    "orchestrator",
    "scheduler",
    "intelligence.repository",
    "sqlalchemy",
)

CORE_FILES = sorted(CORE_DIR.glob("*.py"))


def _forbidden_hit(module: str) -> str | None:
    for name in FORBIDDEN:
        if module == name or module.startswith(name + "."):
            return name
    return None


def _toplevel_imports(path: Path) -> list[tuple[int, str]]:
    """(lineno, module) for every module-level import in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in tree.body:  # module level only — nested/lazy imports are allowed
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append((node.lineno, node.module))
    return found


def test_core_directory_is_populated() -> None:
    # Guard against the parametrization silently covering nothing.
    assert CORE_FILES, "no core/*.py files found"


@pytest.mark.parametrize("path", CORE_FILES, ids=lambda p: p.name)
def test_core_file_has_no_forbidden_imports(path: Path) -> None:
    violations = [
        f"{path.name}:{lineno} imports '{module}' (forbidden: {hit})"
        for lineno, module in _toplevel_imports(path)
        if (hit := _forbidden_hit(module))
    ]
    assert not violations, (
        "core/ must not depend on db/chat/agent layers:\n" + "\n".join(violations)
    )
