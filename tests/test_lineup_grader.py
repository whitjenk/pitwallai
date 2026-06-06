"""Lineup grader: intent routing + extraction + scoring."""

from __future__ import annotations

import pytest

from whatsapp.intent import resolve_intent
from whatsapp.inbound import _extract_lineup


def test_intent_routes_lineup_statement_to_grade() -> None:
    out = resolve_intent("I chose to play limitless and picked HAM, LEC, ANT, RUS, VER and MER, FER")
    assert out is not None and out.startswith("GRADE")
    # A bare chip question (no lineup) still goes to the chip planner.
    assert resolve_intent("should i play limitless?") == "CHIPS LIMITLESS"


def test_extract_lineup_splits_drivers_constructors_chip() -> None:
    drivers, constructors, chip = _extract_lineup(
        "I chose HAM, LEC, ANT, RUS, VER and MER, FER with limitless"
    )
    assert drivers == ["HAM", "LEC", "ANT", "RUS", "VER"]
    assert set(constructors) == {"MER", "FER"}
    assert chip == "limitless"


@pytest.mark.asyncio
async def test_grade_lineup_scores_and_compares(monkeypatch) -> None:
    import intelligence.lineup_grader as lg
    from intelligence.schemas import PracticeSignal

    def _sig(code, pace):
        return PracticeSignal(
            driver_number=0, driver_code=code, session="FP2", setup_sentiment=0.0,
            tire_confidence=0.5, mechanical_flags=[], pace_satisfaction=pace,
            anomaly_flags=[], raw_evidence=[],
        )

    # HAM/LEC/VER/RUS/ANT fastest; everyone else slow.
    signals = {
        "HAM": _sig("HAM", 1.0), "LEC": _sig("LEC", 0.95), "VER": _sig("VER", 0.9),
        "RUS": _sig("RUS", 0.85), "ANT": _sig("ANT", 0.8),
        "NOR": _sig("NOR", 0.3), "PIA": _sig("PIA", 0.25),
    }

    async def _fake_loader(_ck):
        return signals

    monkeypatch.setattr(lg, "load_practice_by_driver", _fake_loader)
    monkeypatch.setattr(lg, "circuit_key_for_race", lambda _rk: "monaco")

    msg = await lg.grade_lineup("2026_monaco", ["HAM", "LEC", "ANT", "RUS", "VER"], ["FER", "MER"], "limitless")
    assert "lineup — graded" in msg
    assert "LIMITLESS" in msg
    assert "5/5" in msg  # matches PitWallAI's top-5 drivers
    assert "projects" in msg
    # No captain stated -> recommends the highest-ceiling driver (HAM).
    assert "🧢" in msg and "HAM" in msg

    # Suboptimal captain is flagged; optimal captain is endorsed.
    sub = await lg.grade_lineup("2026_monaco", ["HAM", "LEC", "ANT", "RUS", "VER"], [], "limitless", captain="ANT")
    assert "I'd captain HAM" in sub
    opt = await lg.grade_lineup("2026_monaco", ["HAM", "LEC", "ANT", "RUS", "VER"], [], "limitless", captain="HAM")
    assert "optimal" in opt


def test_extract_captain_finds_stated_captain() -> None:
    from whatsapp.inbound import _extract_captain

    drivers = ["HAM", "LEC", "ANT", "RUS", "VER"]
    assert _extract_captain("captain HAM", drivers) == "HAM"
    assert _extract_captain("I'll triple VER", drivers) == "VER"
    assert _extract_captain("LEC as captain", drivers) == "LEC"
    assert _extract_captain("no captain mentioned", drivers) is None
