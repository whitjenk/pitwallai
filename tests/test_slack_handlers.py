"""Slack handler tests (brief 006) — no Slack, no network.

Each test calls :func:`slack_app.handlers.handle` directly against a fresh
``tmp_path`` SQLite store. ``core.api.suggest_transfers`` is monkeypatched so
``picks`` never touches OpenF1. Every reply a league-mate gets here is personal,
so each test also asserts the reply is ``ephemeral``.
"""

from __future__ import annotations

import pytest

import store
from core.types import Team as CoreTeam
from slack_app import handlers
from slack_app.reply import EPHEMERAL
from store import db as store_db

_GOOD_TEAM = "team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2"


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the store at an isolated SQLite file for one test."""
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    # Dispose synchronously so the aiosqlite pool isn't finalised later on a
    # closed event loop (which raises a noisy "Event loop is closed" warning).
    if engine is not None:
        engine.sync_engine.dispose()


async def _call(text: str) -> object:
    return await handlers.handle(text, user_id="U1", team_id="T1", display_name="Alice")


# ── help ────────────────────────────────────────────────────────────────────
async def test_help_is_ephemeral_and_lists_commands():
    for text in ("help", ""):
        reply = await _call(text)
        assert reply.visibility == EPHEMERAL
        assert "picks" in reply.text and "team" in reply.text and "forget" in reply.text


async def test_unknown_subcommand_falls_back_to_help():
    reply = await _call("wibble")
    assert reply.visibility == EPHEMERAL
    assert "picks" in reply.text


# ── team: save ────────────────────────────────────────────────────────────────
async def test_team_save_validates_and_persists(tmp_db):
    await store.init_db()
    reply = await _call(_GOOD_TEAM)
    assert reply.visibility == EPHEMERAL
    assert "Saved" in reply.text

    saved = await store.get_team("U1")
    assert saved is not None
    assert saved.drivers == ["HAM", "LEC", "NOR", "PIA", "VER"]
    assert saved.constructors == ["MCL", "FER"]
    assert saved.budget_m == pytest.approx(2.5)
    assert saved.transfers_available == 2
    assert saved.display_name == "Alice"


async def test_team_save_resolves_full_name(tmp_db):
    await store.init_db()
    # "Lewis" must resolve to HAM.
    reply = await _call("team lewis LEC NOR PIA VER MCL FER budget 2.5 transfers 2")
    assert reply.visibility == EPHEMERAL
    assert "Saved" in reply.text
    saved = await store.get_team("U1")
    assert saved is not None and saved.drivers[0] == "HAM"


async def test_team_unknown_driver_code_rejected(tmp_db):
    await store.init_db()
    reply = await _call("team HAM LEC NOR PIA ZZZ MCL FER budget 2.5 transfers 2")
    assert reply.visibility == EPHEMERAL
    assert "ZZZ" in reply.text
    assert "couldn't save" in reply.text.lower()
    assert await store.get_team("U1") is None  # nothing persisted on error


async def test_team_over_budget_rejected(tmp_db):
    await store.init_db()
    reply = await _call("team HAM LEC NOR PIA VER MCL FER budget -5 transfers 2")
    assert reply.visibility == EPHEMERAL
    assert "budget" in reply.text.lower()
    assert await store.get_team("U1") is None


async def test_team_wrong_count_rejected(tmp_db):
    await store.init_db()
    reply = await _call("team HAM LEC NOR MCL FER budget 2.5 transfers 2")
    assert reply.visibility == EPHEMERAL
    assert "drivers" in reply.text.lower()
    assert await store.get_team("U1") is None


# ── team: show ────────────────────────────────────────────────────────────────
async def test_team_show_without_saved_team_hints(tmp_db):
    await store.init_db()
    reply = await _call("team")
    assert reply.visibility == EPHEMERAL
    assert "/pitwall team" in reply.text


async def test_team_show_after_save(tmp_db):
    await store.init_db()
    await _call(_GOOD_TEAM)
    reply = await _call("team")
    assert reply.visibility == EPHEMERAL
    assert "HAM" in reply.text and "MCL" in reply.text


# ── picks ──────────────────────────────────────────────────────────────────────
async def test_picks_without_saved_team_hints(tmp_db):
    await store.init_db()
    reply = await _call("picks")
    assert reply.visibility == EPHEMERAL
    assert "team" in reply.text.lower()


async def test_picks_uses_core_api_with_converted_team(tmp_db, monkeypatch):
    await store.init_db()
    await _call(_GOOD_TEAM)

    captured: dict[str, object] = {}

    async def fake_suggest(team, race_key, client):
        captured["team"] = team
        captured["race_key"] = race_key
        return _fake_pick_output()

    monkeypatch.setattr(handlers, "suggest_transfers", fake_suggest)

    reply = await _call("picks")
    assert reply.visibility == EPHEMERAL
    assert "DRS warm" in reply.text  # the headline from the fake output
    # Handler converted the store team into a core.types.Team.
    assert isinstance(captured["team"], CoreTeam)
    assert captured["team"].drivers == ["HAM", "LEC", "NOR", "PIA", "VER"]
    assert isinstance(captured["race_key"], str) and captured["race_key"]


async def test_picks_degrades_on_error_without_stack_trace(tmp_db, monkeypatch):
    await store.init_db()
    await _call(_GOOD_TEAM)

    async def boom(team, race_key, client):
        raise RuntimeError("openf1 down")

    monkeypatch.setattr(handlers, "suggest_transfers", boom)
    reply = await _call("picks")
    assert reply.visibility == EPHEMERAL
    assert "Couldn't" in reply.text
    assert "Traceback" not in reply.text and "RuntimeError" not in reply.text


# ── forget ──────────────────────────────────────────────────────────────────────
async def test_forget_erases_team(tmp_db):
    await store.init_db()
    await _call(_GOOD_TEAM)
    assert await store.get_team("U1") is not None
    reply = await _call("forget")
    assert reply.visibility == EPHEMERAL
    assert await store.get_team("U1") is None


def _fake_pick_output():
    from core.schemas import PickOutput, PickRecommendation

    return PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="DRS warm and quick in practice",
                confidence=72.0,
                reasoning="Projected to gain on long-run pace.",
                driver_code="PIA",
                transfer_in="PIA",
                transfer_out="VER",
            )
        ],
        personalized=True,
        circuit_note="High-speed circuit.",
        confidence_note="Two practice sessions available.",
        generated_by="rules",
    )
