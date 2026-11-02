"""Honest 'data isn't there' replies for picks/grade/lock/score (brief 012).

Frozen clock + fake core.api functions, so no network. Three situations:
paused (a scheduled OpenF1 lockout), unreachable (a call failed, no pause) and
nothing-yet (the call succeeded but the data genuinely isn't in).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import store
from openf1.health import record_openf1_failure, reset_openf1_health
from slack_app import handlers, reminders
from slack_app.openf1_client import OpenF1Paused
from store import db as store_db

# São Paulo qualifying 18:00–19:00 UTC → pause window 17:30–19:30.
_DURING_PAUSE = datetime(2026, 11, 7, 18, 30, tzinfo=UTC)
_WINDOW_CLOSE = datetime(2026, 11, 7, 19, 30, tzinfo=UTC)
_NO_PAUSE = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)  # mid-week, no session
_LINEUP = "HAM LEC ANT RUS VER MER FER captain HAM 3x"


@pytest.fixture(autouse=True)
def _reset_health():
    reset_openf1_health()
    yield
    reset_openf1_health()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


def _freeze(monkeypatch, now):
    monkeypatch.setattr(handlers, "_now", lambda: now)


async def _call(text):
    return await handlers.handle(text, user_id="U1", team_id="T1", display_name="Alice")


_GOOD_TEAM = "team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2"


# ── picks ─────────────────────────────────────────────────────────────────────
async def test_picks_paused(tmp_db, monkeypatch):
    await store.init_db()
    await _call(_GOOD_TEAM)
    _freeze(monkeypatch, _DURING_PAUSE)

    async def paused(team, race_key, client):
        raise OpenF1Paused(_WINDOW_CLOSE)

    monkeypatch.setattr(handlers, "suggest_transfers", paused)
    reply = await _call("picks")
    assert "<!date^" in reply.text  # a Slack time token the reader sees locally
    assert "Qualifying" in reply.text
    assert "practice" not in reply.text.lower()


async def test_picks_unreachable(tmp_db, monkeypatch):
    await store.init_db()
    await _call(_GOOD_TEAM)
    _freeze(monkeypatch, _NO_PAUSE)

    async def boom(team, race_key, client):
        raise RuntimeError("openf1 down")

    monkeypatch.setattr(handlers, "suggest_transfers", boom)
    reply = await _call("picks")
    assert "couldn't be reached" in reply.text.lower()
    assert "practice" not in reply.text.lower()


# ── grade ─────────────────────────────────────────────────────────────────────
async def test_grade_paused(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _DURING_PAUSE)

    async def boom(lineup, race_key, client):
        raise RuntimeError("down")

    monkeypatch.setattr(handlers, "grade_lineup", boom)
    reply = await _call(f"grade {_LINEUP}")
    assert "<!date^" in reply.text and "Qualifying" in reply.text
    assert "practice" not in reply.text.lower()


async def test_grade_unreachable(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)

    async def boom(lineup, race_key, client):
        raise RuntimeError("down")

    monkeypatch.setattr(handlers, "grade_lineup", boom)
    reply = await _call(f"grade {_LINEUP}")
    assert "couldn't be reached" in reply.text.lower()
    assert "practice" not in reply.text.lower()


async def test_grade_nothing_yet(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)

    async def no_data(lineup, race_key, client):
        return {}  # call succeeded, but no practice pace yet

    monkeypatch.setattr(handlers, "grade_lineup", no_data)
    reply = await _call(f"grade {_LINEUP}")
    assert "No practice laps" in reply.text
    assert "FP1 starts" in reply.text and "<!date^" in reply.text


async def test_grade_unreachable_uses_health_without_an_exception(tmp_db, monkeypatch):
    """Even if a stale cache swallowed the error, repeated failures read as down."""
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)
    for _ in range(3):
        record_openf1_failure(RuntimeError("flaky"))

    async def no_data(lineup, race_key, client):
        return {}

    monkeypatch.setattr(handlers, "grade_lineup", no_data)
    reply = await _call(f"grade {_LINEUP}")
    assert "couldn't be reached" in reply.text.lower()


# ── lock (the bot's own pick line) ────────────────────────────────────────────
async def test_lock_nothing_yet_bot_line(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)

    async def no_proj(race_key, client):
        return {}

    monkeypatch.setattr(reminders, "project_race", no_proj)
    confirm, _channel = await _call(f"lock {_LINEUP}")
    assert "No practice laps" in confirm.text  # lock still saved, no model pick


async def test_lock_paused_bot_line(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _DURING_PAUSE)

    async def paused(race_key, client):
        raise OpenF1Paused(_WINDOW_CLOSE)

    monkeypatch.setattr(reminders, "project_race", paused)
    confirm, _channel = await _call(f"lock {_LINEUP}")
    assert "<!date^" in confirm.text and "Qualifying" in confirm.text
    # The lineup was still locked despite the paused projection.
    race_key = handlers._next_race_key(_DURING_PAUSE)
    assert await store.get_locked("U1", race_key) is not None


# ── score ─────────────────────────────────────────────────────────────────────
async def _lock_for_score(monkeypatch):
    async def proj(race_key, client):
        return {"race_key": race_key, "top_drivers": ["LEC"], "top_constructors": ["FER"], "captain": "LEC"}

    monkeypatch.setattr(reminders, "project_race", proj)
    await _call(f"lock {_LINEUP}")


async def test_score_paused(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)
    await _lock_for_score(monkeypatch)
    _freeze(monkeypatch, _DURING_PAUSE)

    async def boom(lineup, race_key, client):
        raise RuntimeError("down")

    monkeypatch.setattr(handlers, "score_lineup", boom)
    reply = await _call("score")
    assert "<!date^" in reply.text and "Qualifying" in reply.text
    assert "practice" not in reply.text.lower()


async def test_score_nothing_yet_not_classified(tmp_db, monkeypatch):
    await store.init_db()
    _freeze(monkeypatch, _NO_PAUSE)
    await _lock_for_score(monkeypatch)

    async def not_in(lineup, race_key, client):
        return None  # race not classified yet

    monkeypatch.setattr(handlers, "score_lineup", not_in)
    reply = await _call("score")
    assert "hasn't been classified" in reply.text
    assert "practice" not in reply.text.lower()
