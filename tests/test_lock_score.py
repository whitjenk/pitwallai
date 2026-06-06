"""LOCK / SCORE intent routing + scoring math."""

from __future__ import annotations

import pytest

from whatsapp.intent import resolve_intent


def test_intent_routes_lock_and_score() -> None:
    lock = resolve_intent("lock in HAM, LEC, ANT, RUS, VER and MER, FER with limitless")
    assert lock is not None and lock.startswith("LOCK")
    assert resolve_intent("score my lineup") == "SCORE"
    assert resolve_intent("did i beat you?") == "SCORE"
    # A stated lineup is preserved for the SCORE handler to parse.
    stated = resolve_intent("score HAM, LEC, ANT, RUS, VER and MER, FER at melbourne")
    assert stated is not None and stated.startswith("SCORE ")


def test_intent_routes_record() -> None:
    assert resolve_intent("show my scorecard") == "RECORD"
    assert resolve_intent("what's my record vs you") == "RECORD"


@pytest.mark.asyncio
async def test_record_aggregates_scored_lineups(monkeypatch) -> None:
    import whatsapp.inbound as ib

    class _Row:
        def __init__(self, rk, y, m, cap):
            self.race_key, self.your_points, self.model_points, self.capture_pct = rk, y, m, cap

    rows = [_Row("2026_melbourne", 173, 58, 99), _Row("2026_suzuka", 116, 163, 68)]

    async def _fake_list(_phone):
        return rows

    monkeypatch.setattr(ib, "_handle_record", ib._handle_record)  # keep reference
    import intelligence.repository as repo

    monkeypatch.setattr(repo, "list_scored_lineups", _fake_list)
    msg = await ib._handle_record("+1")
    assert "2 race(s)" in msg
    assert "84%" in msg  # avg of 99 and 68
    assert "1-1" in msg  # one win, one loss vs the model
    assert "99%" in msg  # best


def test_resolve_race_key_from_text() -> None:
    from whatsapp.inbound import _resolve_race_key

    assert _resolve_race_key("at melbourne") == "2026_melbourne"
    assert _resolve_race_key("the australian gp") == "2026_melbourne"
    assert _resolve_race_key("for monaco this week") == "2026_monaco"
    assert _resolve_race_key("just my lineup") is None


@pytest.mark.asyncio
async def test_score_against_result_math(monkeypatch) -> None:
    import intelligence.lineup_grader as lg

    class _FakeClient:
        async def find_session_key(self, **_):
            return 999

        async def get_session_results(self, _sk):
            from openf1.models import SessionResultRow

            return [
                SessionResultRow(session_key=999, driver_number=44, position=1),  # HAM P1
                SessionResultRow(session_key=999, driver_number=16, position=2),  # LEC P2
                SessionResultRow(session_key=999, driver_number=12, position=11),  # ANT P11 (0)
            ]

        async def get_drivers(self, _sk):
            from openf1.models import DriverSessionRow

            return [
                DriverSessionRow(session_key=999, driver_number=44, name_acronym="HAM"),
                DriverSessionRow(session_key=999, driver_number=16, name_acronym="LEC"),
                DriverSessionRow(session_key=999, driver_number=12, name_acronym="ANT"),
            ]

    monkeypatch.setattr(lg, "OpenF1Client", _FakeClient, raising=False)
    # patch the lazily-imported client used inside the function
    import openf1.client as oc

    monkeypatch.setattr(oc, "OpenF1Client", _FakeClient)

    res = await lg.score_against_result(
        "2026_melbourne", ["HAM", "LEC", "ANT"], [], chip=None, captain="HAM"
    )
    assert res is not None
    # HAM P1=25, LEC P2=18, ANT P11=0; captain HAM doubles -> +25 bonus.
    assert res["driver_pts"] == {"HAM": 25, "LEC": 18, "ANT": 0}
    assert res["captain"] == "HAM"
    assert res["captain_bonus"] == 25
    assert res["total"] == 25 + 18 + 0 + 25


def test_perfect_lineup_from_positions() -> None:
    from intelligence.lineup_grader import perfect_lineup_from_positions

    # HAM P1=25, RUS P2=18, LEC P3=15, plus filler.
    positions = {"HAM": 1, "RUS": 2, "LEC": 3, "NOR": 4, "PIA": 5, "ALB": 15}
    perfect = perfect_lineup_from_positions(positions)
    assert perfect["drivers"][0] == "HAM"  # top scorer leads
    assert "ALB" not in perfect["drivers"]  # P15 (0 pts) not in the best five
    # Captain bonus = best driver's points (HAM, +25); total must beat raw sum.
    assert perfect["total"] >= 25 + 18 + 15 + 12 + 10 + 25
