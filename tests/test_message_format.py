"""Mandatory char-limit tests for WhatsApp formatters."""

from __future__ import annotations

from datetime import UTC, datetime

from intelligence.schemas import PickOutput, PickRecommendation
from scheduler.calendar import get_race_weekend
from whatsapp.message_format import (
    GENERIC_MAX_CHARS,
    PERSONALIZED_MAX_CHARS,
    RECAP_MAX_CHARS,
    SEASON_RECAP_MAX_CHARS,
    format_generic_picks,
    format_personalized_picks,
    format_recap_message,
    format_season_recap_message,
)


def test_personalized_includes_constructor_pit_tendency_when_sampled() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    output = PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="Swap STR → LEC. +9 expected pts.",
                confidence=74.0,
                reasoning="Leclerc P4; historical pit tendency noted.",
                driver_code="LEC",
                predicted_points_delta=9.0,
                transfer_out="STR",
                transfer_in="LEC",
                constructor_strategy_note=(
                    "FER pit tendency (5 races): early 75% in pace-competitive stops (6), "
                    "cross-team undercut 80% (8 attempts)"
                ),
            ),
        ],
        personalized=True,
        circuit_note="Monaco",
        confidence_note="Strong signals",
        generated_by="quali_strategist",
    )
    msg = format_personalized_picks(weekend, output, timezone="Europe/London")
    assert "Historical pit trend (FER)" in msg
    assert "pace-competitive" in msg
    assert "Monaco" in msg
    assert len(msg) <= PERSONALIZED_MAX_CHARS


def test_personalized_omits_pit_tendency_without_min_samples() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    output = PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="Swap STR → LEC. +9 expected pts.",
                confidence=74.0,
                reasoning="Leclerc P4.",
                driver_code="LEC",
                predicted_points_delta=9.0,
                transfer_out="STR",
                transfer_in="LEC",
                constructor_strategy_note=(
                    "FER pit tendency (2 races): early 100% in pace-competitive stops (2), "
                    "cross-team undercut 50% (1 attempts)"
                ),
            ),
        ],
        personalized=True,
        circuit_note="Monaco",
        confidence_note="OK",
        generated_by="quali_strategist",
    )
    msg = format_personalized_picks(weekend, output, timezone="Europe/London")
    assert "Historical pit trend" not in msg


def test_personalized_under_400_chars() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    output = PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="Swap STR → ALB. Saves $0.3M. +7 expected pts.",
                confidence=71.0,
                reasoning="Albon P8 on grid, clean practice, circuit suits his style.",
                driver_code="ALB",
                predicted_points_delta=7.0,
                transfer_out="STR",
                transfer_in="ALB",
            ),
            PickRecommendation(
                rank=2,
                headline="Swap MAG → HUL. Saves $0.1M. +4 expected pts.",
                confidence=58.0,
                reasoning="Hulkenberg steady long runs; Magnussen FP2 anomalies.",
                driver_code="HUL",
                predicted_points_delta=4.0,
                transfer_out="MAG",
                transfer_in="HUL",
            ),
        ],
        personalized=True,
        circuit_note="Monaco",
        confidence_note="Strong signals",
        generated_by="rules",
    )
    msg = format_personalized_picks(weekend, output, timezone="Europe/London")
    assert len(msg) <= PERSONALIZED_MAX_CHARS


def test_generic_under_350_chars() -> None:
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    output = PickOutput(
        picks=[
            PickRecommendation(
                rank=i,
                headline=f"Target {code}",
                confidence=conf,
                reasoning=f"{code} strong practice and qualifying position for Monaco street circuit traits.",
                driver_code=code,
            )
            for i, (code, conf) in enumerate([("NOR", 78.0), ("LEC", 65.0), ("ALB", 52.0)], start=1)
        ],
        personalized=False,
        circuit_note="Monaco",
        confidence_note="OK",
        generated_by="rules",
    )
    msg = format_generic_picks(weekend, output, timezone="America/New_York")
    assert len(msg) <= GENERIC_MAX_CHARS


def test_recap_under_300_chars() -> None:
    msg = format_recap_message(
        circuit_name="Monaco Grand Prix",
        correct_count=2,
        total_picks=3,
        season_accuracy_pct=67.5,
        session_note="PitWallAI GP picks: 67% hit · +2.3 avg race pts",
        swap_note="Best swap netted +12 pts",
        next_race_name="Barcelona-Catalunya Grand Prix",
        days_until_next=7,
        nudge_team=True,
    )
    assert len(msg) <= RECAP_MAX_CHARS


def test_long_reasoning_truncated_not_bloated() -> None:
    weekend = get_race_weekend("2026_silverstone")
    assert weekend is not None
    long_reason = "x" * 200
    output = PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="Target VER",
                confidence=88.0,
                reasoning=long_reason,
                driver_code="VER",
            )
        ],
        personalized=False,
        circuit_note="",
        confidence_note="",
        generated_by="rules",
    )
    msg = format_generic_picks(weekend, output, timezone="UTC")
    assert len(msg) <= GENERIC_MAX_CHARS


def test_season_recap_shareable_message_limit() -> None:
    msg = format_season_recap_message(
        season=2026,
        personalized_accuracy_pct=61.0,
        community_accuracy_pct=58.0,
        best_call="ALB at Monaco (+12 pts)",
        worst_call="SAI at Silverstone (-9 pts)",
        biggest_signal="practice radio sentiment was 71% predictive",
        share_url="https://pitwallai.app/you/abc123token",
    )
    assert "Season complete" in msg
    assert "Reply SHARE" in msg
    assert len(msg) <= SEASON_RECAP_MAX_CHARS
