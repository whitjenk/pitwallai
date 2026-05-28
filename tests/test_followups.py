"""Tests for Phase 7 follow-up hardening."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from db.migrate import _COLUMN_MIGRATIONS
from onboarding.monaco_calendar import MONACO_2024_REHEARSAL, MONACO_SESSION_KEY
from onboarding.monaco_messages import build_fp2_delta_message, build_welcome_context_message
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO
from whatsapp.app_runtime import PickRuntime, get_pick_runtime, register_fastapi_app


def test_phase7_column_migrations_defined() -> None:
    assert any("pick_status" in s for s in _COLUMN_MIGRATIONS)
    assert any("rehearsal_complete" in s for s in _COLUMN_MIGRATIONS)
    assert any("share_cards_private" in s for s in _COLUMN_MIGRATIONS)


def test_monaco_rehearsal_constants() -> None:
    assert MONACO_SESSION_KEY == 9158
    assert MONACO_2024_REHEARSAL.race_key == "2024_monaco"
    assert MONACO_REHEARSAL_SCENARIO.events[0].session_key == MONACO_SESSION_KEY


def test_monaco_welcome_mentions_session() -> None:
    msg = build_welcome_context_message()
    assert "9158" in msg
    assert "Monaco 2024" in msg


def test_monaco_fp2_delta_format() -> None:
    msg = build_fp2_delta_message(lock_label="Sat 14:00")
    assert "NOR" in msg
    assert "LEC" in msg
    assert len(msg) <= 280


def test_get_pick_runtime_lazy_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import whatsapp.app_runtime as ar

    stub = PickRuntime(agent=MagicMock(), vector_store=MagicMock(), settings=MagicMock())
    monkeypatch.setattr(ar, "_lazy_pick_runtime", lambda: stub)
    ar._app = None
    ar._lazy_runtime = None
    runtime = get_pick_runtime(allow_lazy=True)
    assert runtime is stub


def test_register_fastapi_app_exposes_runtime() -> None:
    import whatsapp.app_runtime as ar

    app = MagicMock()
    app.state.agent = MagicMock()
    app.state.vector_store = MagicMock()
    app.state.settings = MagicMock()
    register_fastapi_app(app)
    runtime = get_pick_runtime(allow_lazy=False)
    assert runtime is not None
    assert runtime.agent is app.state.agent
    ar._app = None
    ar._lazy_runtime = None
