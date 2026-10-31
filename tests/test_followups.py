"""Tests for Phase 7 follow-up hardening."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from db.migrate import _COLUMN_MIGRATIONS
from whatsapp.app_runtime import PickRuntime, get_pick_runtime, register_fastapi_app


def test_phase7_column_migrations_defined() -> None:
    assert any("pick_status" in s for s in _COLUMN_MIGRATIONS)
    assert any("rehearsal_complete" in s for s in _COLUMN_MIGRATIONS)
    assert any("share_cards_private" in s for s in _COLUMN_MIGRATIONS)


def test_get_pick_runtime_lazy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import whatsapp.app_runtime as ar

    stub = PickRuntime(settings=MagicMock())
    monkeypatch.setattr(ar, "_lazy_pick_runtime", lambda: stub)
    ar._app = None
    ar._lazy_runtime = None
    runtime = get_pick_runtime(allow_lazy=True)
    assert runtime is stub


def test_register_fastapi_app_exposes_runtime() -> None:
    import whatsapp.app_runtime as ar

    app = MagicMock()
    app.state.settings = MagicMock()
    register_fastapi_app(app)
    runtime = get_pick_runtime(allow_lazy=False)
    assert runtime is not None
    assert runtime.settings is app.state.settings
    ar._app = None
    ar._lazy_runtime = None
