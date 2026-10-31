"""The new stack runs with every legacy package absent (brief 010).

Two guarantees, so that deleting the legacy folders (brief 011) can't quietly
break the Slack bot:

1. *Static* — no file under the new packages (``core``, ``store``, ``slack_app``,
   ``openf1``, ``feeds``) imports a legacy package **anywhere**, including inside
   a function body. ``test_core_boundary.py`` only checks top-level imports; the
   old code hid its ties in function-local imports precisely so that test stayed
   green. This walks every ``import`` node.

2. *Runtime* — with those legacy packages hard-blocked from importing, we import
   ``slack_app.handlers`` and run **every** ``/pitwall`` subcommand against a
   temp store and a fake OpenF1 client. All must return a reply, not blow up on
   a missing legacy module.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

# Packages the new stack must never reach into. Matches the folders brief 011
# deletes, plus the modules being folded into ``core`` with shims left behind.
LEGACY_PACKAGES = frozenset(
    {
        "whatsapp",
        "agents",
        "orchestrator",
        "scheduler",
        "db",
        "api",
        "intelligence",
        "models",
        "fantasy",
        "circuits",
        "utils",
        "sharing",
        "onboarding",
    }
)

# The new packages that must stand on their own once legacy is gone.
NEW_PACKAGES = ("core", "store", "slack_app", "openf1", "feeds")

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ── 1. Static: no legacy import anywhere, not even inside a function ───────────
def _imported_top_levels(path: Path) -> list[tuple[int, str]]:
    """(lineno, top-level package) for every import node in a file.

    Walks the whole tree, so a ``from intelligence.x import y`` tucked inside a
    function is caught too. Relative imports (``from . import x``) stay inside
    the file's own package and are skipped.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.lineno, node.module.split(".")[0]))
    return found


def _new_package_files() -> list[Path]:
    files: list[Path] = []
    for pkg in NEW_PACKAGES:
        files.extend(sorted((_REPO_ROOT / pkg).rglob("*.py")))
    return files


def test_new_packages_exist() -> None:
    # Guard against the sweep silently covering nothing.
    assert _new_package_files(), "no new-package *.py files found"


def test_no_legacy_imports_static() -> None:
    offenders: list[str] = []
    for path in _new_package_files():
        rel = path.relative_to(_REPO_ROOT)
        for lineno, top in _imported_top_levels(path):
            if top in LEGACY_PACKAGES:
                offenders.append(f"{rel}:{lineno} imports legacy '{top}'")
    assert not offenders, "new code still imports legacy packages:\n" + "\n".join(offenders)


# ── 2. Runtime: handlers work with legacy packages blocked from importing ─────
class _LegacyBlocker:
    """A meta-path finder that refuses to import any legacy package."""

    def __init__(self, blocked: frozenset[str]) -> None:
        self._blocked = blocked

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if fullname.split(".")[0] in self._blocked:
            raise ModuleNotFoundError(
                f"legacy package {fullname!r} is blocked by test_no_legacy_imports"
            )
        return None  # defer to the normal finders for everything else


class _FakeOpenF1Client:
    """Stand-in client: no network, nothing classified yet.

    ``find_session_key`` returning ``None`` makes every ``core.api`` entry point
    take its graceful "no data yet" path, so each handler returns a reply
    without a real HTTP call.
    """

    async def find_session_key(self, **_kwargs) -> None:  # noqa: ANN003
        return None

    async def get_sessions(self, **_kwargs):  # noqa: ANN003
        return []

    async def get_laps(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
        return []

    async def get_session_results(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
        return []

    async def get_drivers(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
        return []


# Every subcommand, with arguments that exercise parsing and formatting.
_COMMANDS = [
    "help",
    "team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2",
    "team",
    "picks",
    "grade HAM LEC ANT RUS VER MER FER captain HAM 3x",
    "lock HAM LEC ANT RUS VER MER FER captain HAM",
    "score",
    "record",
    "forget",
    "nonsense-subcommand",
]


async def _run_every_handler(handlers, reply_cls) -> None:
    await handlers.store.init_db()
    for text in _COMMANDS:
        result = await handlers.handle(text, "U_TEST", "T_TEST", "Tester")
        replies = result if isinstance(result, list) else [result]
        assert replies, f"{text!r} returned no reply"
        for reply in replies:
            assert isinstance(reply, reply_cls), f"{text!r} returned {type(reply)!r}"


def _run_handlers_under_blocker() -> None:
    """Install the blocker, import the handlers fresh, and exercise them all.

    Runs in a dedicated subprocess (see the test below) so the blocker meets a
    clean import graph and nothing it evicts leaks into other tests.
    """
    sys.meta_path.insert(0, _LegacyBlocker(LEGACY_PACKAGES))
    handlers = importlib.import_module("slack_app.handlers")
    reply_cls = importlib.import_module("slack_app.reply").Reply
    handlers.build_client = lambda: _FakeOpenF1Client()
    asyncio.run(_run_every_handler(handlers, reply_cls))


def test_handlers_run_with_legacy_blocked(tmp_path) -> None:
    # A fresh interpreter, so the blocker sees every import of the handler graph
    # from scratch — and so evicting/blocking legacy can't pollute this session.
    env = {
        **os.environ,
        "PYTHONPATH": str(_REPO_ROOT),
        "PITWALL_DB_PATH": str(tmp_path / "pitwall.sqlite"),
        "PITWALL_DECODE_BACKEND": "rules",
    }
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--run-handlers"],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        "handlers failed to run with legacy packages blocked:\n"
        + proc.stdout
        + proc.stderr
    )


if __name__ == "__main__":  # invoked as a subprocess by the test above
    if "--run-handlers" in sys.argv:
        _run_handlers_under_blocker()
