"""Demo picks for local dashboard click-through when DATABASE_URL is unset."""

from __future__ import annotations

from datetime import UTC, datetime

from circuits.profiles import get_circuit_profile
from intelligence.active_weekend import ActiveWeekend
from intelligence.picks_pipeline import PicksRunResult
from intelligence.schemas import PickOutput, PickRecommendation, PracticeSignal
from models.pick_explanation import PickExplanation, SignalSource


def build_demo_picks_result() -> PicksRunResult:
    """Monaco-style demo output with explanation cards (no OpenF1 / DB)."""
    circuit = get_circuit_profile("monaco")
    assert circuit is not None
    weekend = ActiveWeekend(
        circuit_key="monaco",
        display_name="Monaco Grand Prix",
        openf1_circuit_name="Monaco",
        year=2024,
        race_session_key=9158,
        qualifying_session_key=9157,
        meeting_key=1221,
        race_start=datetime(2024, 5, 26, 13, 0, tzinfo=UTC),
    )
    pick = PickRecommendation(
        rank=1,
        headline="Swap STR → LEC. +9 expected pts.",
        confidence=74.0,
        reasoning="Leclerc P4; practice sentiment positive; quali aligned.",
        driver_code="LEC",
        predicted_points_delta=9.0,
        transfer_out="STR",
        transfer_in="LEC",
        ownership_tier="LOW",
        is_contrarian=True,
        league_strategy_applied="ATTACK",
        explanation=PickExplanation(
            driver_code="LEC",
            primary_signal=(
                "FP2: setup sentiment +0.55, tyre confidence 70% — "
                "engineer noted rear stability in S2."
            ),
            signal_source=SignalSource.PRACTICE,
            risk_note="Street circuit — limited overtaking; history mixed at Monaco.",
            league_angle="Contrarian — upside if rivals play chalk this weekend.",
        ),
    )
    return PicksRunResult(
        output=PickOutput(
            picks=[pick],
            personalized=True,
            circuit_note="Monaco: tight quali — constructor pit windows matter.",
            confidence_note="Demo data for local click-through (no DATABASE_URL).",
            generated_by="demo",
        ),
        weekend=weekend,
        circuit=circuit,
        generated_at=datetime.now(tz=UTC),
        practice_signal_count=2,
    )
