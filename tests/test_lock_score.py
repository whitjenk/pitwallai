"""LOCK / SCORE intent routing + scoring math."""

from __future__ import annotations

import pytest

from whatsapp.intent import resolve_intent


def test_intent_routes_lock_and_score() -> None:
    lock = resolve_intent("lock in HAM, LEC, ANT, RUS, VER and MER, FER with limitless")
    assert lock is not None and lock.startswith("LOCK")
    assert resolve_intent("score my lineup") == "SCORE"
    assert resolve_intent("did i beat you?") == "SCORE"


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
