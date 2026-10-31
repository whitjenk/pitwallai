"""Slack handler tests (brief 006) — no Slack, no network.

Each test calls :func:`slack_app.handlers.handle` directly against a fresh
``tmp_path`` SQLite store. ``core.api.suggest_transfers`` is monkeypatched so
``picks`` never touches OpenF1. Every reply a league-mate gets here is personal,
so each test also asserts the reply is ``ephemeral``.
"""

from __future__ import annotations

import pytest

import store
from core.types import Lineup as CoreLineup
from core.types import Team as CoreTeam
from slack_app import handlers
from slack_app.reply import EPHEMERAL, IN_CHANNEL
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


# ── league commands (brief 007): grade / lock / score / record ────────────────
_LINEUP = "HAM LEC ANT RUS VER MER FER captain HAM 3x"

# A model pick with no HAM, so a HAM-containing lineup can be scored as beating
# it deterministically in the fakes below.
_FAKE_PROJECTION = {
    "race_key": "x",
    "top_drivers": ["LEC", "NOR", "PIA", "RUS", "ANT"],
    "top_constructors": ["MCL", "FER"],
    "captain": "LEC",
}


async def _fake_project_race(race_key, client):
    return dict(_FAKE_PROJECTION, race_key=race_key)


async def _fake_grade(lineup, race_key, client):
    _fake_grade.seen = lineup  # type: ignore[attr-defined]
    return {
        "race_key": race_key,
        "driver_points": {d: 20.0 for d in lineup.drivers},
        "constructor_points": {},
        "captain": lineup.captain,
        "captain_bonus": 18.0,
        "projected_total": 140.0,
        "model_top_drivers": ["LEC", "NOR", "PIA", "VER", "HAM"],
        "drivers_matching_model": [d for d in lineup.drivers if d in {"LEC", "VER", "HAM"}],
    }


async def _fake_score(lineup, race_key, client):
    # A HAM lineup outscores the HAM-less model pick, so `score`/`record` have a
    # deterministic winner without any network.
    total = 90 if "HAM" in lineup.drivers else 70
    return {
        "race_key": race_key,
        "total": total,
        "driver_points": {d: total / max(len(lineup.drivers), 1) for d in lineup.drivers},
        "constructor_points": {},
        "captain": lineup.captain,
        "captain_bonus": 12,
        "positions": {"HAM": 1, "VER": 2},
        "perfect": {"total": 120, "drivers": ["VER", "HAM"], "constructors": ["MER", "FER"]},
    }


async def test_grade_posts_to_channel_with_chip_and_captain(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(handlers, "grade_lineup", _fake_grade)
    reply = await _call(f"grade {_LINEUP}")
    assert reply.visibility == IN_CHANNEL
    # The handler parsed the chip and captain out of the free text.
    seen = _fake_grade.seen  # type: ignore[attr-defined]
    assert isinstance(seen, CoreLineup)
    assert seen.captain == "HAM"
    assert seen.chip == "extra_drs"  # "3x"
    assert seen.drivers == ["HAM", "LEC", "ANT", "RUS", "VER"]
    assert "graded" in reply.text.lower()


async def test_grade_without_lineup_hints_privately(tmp_db):
    await store.init_db()
    reply = await _call("grade")
    assert reply.visibility == EPHEMERAL  # an input error is personal
    assert "lineup" in reply.text.lower()


async def test_lock_is_private_plus_a_channel_line_that_hides_the_lineup(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(handlers, "project_race", _fake_project_race)
    replies = await _call(f"lock {_LINEUP}")
    assert isinstance(replies, list) and len(replies) == 2

    confirm, channel = replies
    # Confirmation is private and shows the lineup back to the user.
    assert confirm.visibility == EPHEMERAL
    assert "HAM" in confirm.text and "Locked" in confirm.text
    # The channel line is public, names the user, and reveals no picks.
    assert channel.visibility == IN_CHANNEL
    assert "<@U1>" in channel.text and "locked in" in channel.text.lower()
    for code in ("HAM", "LEC", "ANT", "RUS", "VER", "MER", "FER"):
        assert code not in channel.text


async def test_lock_twice_replaces(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(handlers, "project_race", _fake_project_race)
    await _call(f"lock {_LINEUP}")
    race_key = handlers._next_race_key()
    first = await store.get_locked("U1", race_key)
    assert first is not None and first.drivers == ["HAM", "LEC", "ANT", "RUS", "VER"]

    # Lock a different squad for the same race — it replaces, not duplicates.
    await _call("lock NOR PIA ALO SAI VER MCL RBR captain NOR")
    locked = [
        lk
        for w in handlers.race_calendar()
        if (lk := await store.get_locked("U1", w.race_key)) is not None
    ]
    assert len(locked) == 1
    assert locked[0].drivers == ["NOR", "PIA", "ALO", "SAI", "VER"]


async def test_score_with_nothing_locked_hints(tmp_db):
    await store.init_db()
    reply = await _call("score")
    assert reply.visibility == EPHEMERAL  # personal: nothing to post publicly
    assert "lock" in reply.text.lower()


async def test_score_posts_result_with_bot_and_perfect(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(handlers, "project_race", _fake_project_race)
    monkeypatch.setattr(handlers, "score_lineup", _fake_score)
    await _call(f"lock {_LINEUP}")

    reply = await _call("score")
    assert reply.visibility == IN_CHANNEL
    assert "90" in reply.text  # your total
    assert "70" in reply.text  # the bot's total
    assert "120" in reply.text  # the perfect lineup's total
    assert "beat me" in reply.text.lower()


async def test_record_with_zero_races_hints(tmp_db):
    await store.init_db()
    reply = await _call("record")
    assert reply.visibility == EPHEMERAL  # nothing to post to the channel yet
    assert "lock" in reply.text.lower()


async def test_record_tallies_wins_against_the_bot(tmp_db, monkeypatch):
    await store.init_db()
    monkeypatch.setattr(handlers, "project_race", _fake_project_race)
    monkeypatch.setattr(handlers, "score_lineup", _fake_score)
    await _call(f"lock {_LINEUP}")

    reply = await _call("record")
    assert reply.visibility == IN_CHANNEL
    assert "1-0" in reply.text  # one race locked and won against the bot


async def test_help_lists_league_commands():
    reply = await _call("help")
    assert reply.visibility == EPHEMERAL
    for cmd in ("grade", "lock", "score", "record"):
        assert cmd in reply.text


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
