"""Tests for low-conviction detection and message rendering."""

from __future__ import annotations

from intelligence.conviction import (
    assess_conviction,
    low_conviction_message,
)
from intelligence.schemas import PickRecommendation, PracticeSignal


def _pick(confidence: float, code: str = "NOR") -> PickRecommendation:
    return PickRecommendation(
        rank=1,
        headline=f"Pick {code}",
        confidence=confidence,
        reasoning="test",
        driver_code=code,
    )


def test_strong_picks_are_high_conviction() -> None:
    picks = [_pick(80), _pick(75, "VER"), _pick(72, "LEC")]
    assessment = assess_conviction(picks)
    assert not assessment.is_low_conviction


def test_low_avg_confidence_triggers_low_conviction() -> None:
    picks = [_pick(45), _pick(48, "VER"), _pick(50, "LEC")]
    assessment = assess_conviction(picks)
    assert assessment.is_low_conviction
    assert any("avg" in r for r in assessment.reasons)


def test_too_few_picks_triggers_low_conviction() -> None:
    picks = [_pick(85), _pick(80, "VER")]
    assessment = assess_conviction(picks)
    assert assessment.is_low_conviction


def test_high_confidence_spread_triggers_low_conviction() -> None:
    picks = [_pick(90), _pick(82, "VER"), _pick(55, "LEC")]
    assessment = assess_conviction(picks)
    assert assessment.is_low_conviction


def test_sparse_practice_signals_trigger_low_conviction() -> None:
    picks = [_pick(85), _pick(80, "VER"), _pick(75, "LEC")]
    sparse_signals = {
        "NOR": PracticeSignal(
            driver_number=4, driver_code="NOR", session="FP2",
            setup_sentiment=0.5, tire_confidence=0.7, pace_satisfaction=0.6,
        )
    }
    assessment = assess_conviction(picks, practice_signals=sparse_signals)
    assert assessment.is_low_conviction
    assert any("practice" in r for r in assessment.reasons)


def test_low_conviction_message_includes_race_name_and_reason() -> None:
    picks = [_pick(40), _pick(45, "VER"), _pick(42, "LEC")]
    assessment = assess_conviction(picks)
    msg = low_conviction_message(assessment, "Monaco GP")
    assert "Monaco GP" in msg
    assert "low conviction" in msg.lower()
    assert "Not financial advice" in msg
