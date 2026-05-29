"""Tests for pick explanation cards (Bet 1)."""

from __future__ import annotations

from circuits.profiles import get_circuit_profile
from intelligence.explanation_builder import (
    ExplanationBuildContext,
    build_explanation,
)
from intelligence.schemas import PickRecommendation, PracticeSignal
from models.pick_explanation import PickExplanation, SignalSource


def _pick(**kwargs) -> PickRecommendation:
    base = dict(
        rank=1,
        headline="Target NOR",
        confidence=72.0,
        reasoning="Composite score.",
        driver_code="NOR",
    )
    base.update(kwargs)
    return PickRecommendation(**base)


def _ctx(**kwargs) -> ExplanationBuildContext:
    return ExplanationBuildContext(
        race_key="2026_monaco",
        circuit_key="monaco",
        circuit=get_circuit_profile("monaco"),
        **kwargs,
    )


def test_radio_signal_wins_over_practice() -> None:
    practice = PracticeSignal(
        driver_number=1,
        driver_code="NOR",
        session="FP2",
        setup_sentiment=0.5,
        tire_confidence=0.7,
        mechanical_flags=[],
        pace_satisfaction=0.6,
        anomaly_flags=["teammate_gap_0.45s_FP2"],
        raw_evidence=["Tyre deg high on rears — engineer noted understeer in S2."],
    )
    pick = _pick(driver_code="NOR", ownership_tier="LOW", is_contrarian=True)
    explanation = build_explanation(
        pick,
        _ctx(practice_by_driver={"NOR": practice}, quali_grid={"NOR": 2}),
    )
    assert explanation is not None
    assert explanation.signal_source == SignalSource.RADIO
    assert "Tyre deg" in explanation.primary_signal or "understeer" in explanation.primary_signal


def test_returns_none_when_no_grounded_signal() -> None:
    pick = _pick(driver_code="BOT", confidence=48.0)
    explanation = build_explanation(
        pick,
        ExplanationBuildContext(race_key="2026_test", circuit_key="test_circuit"),
    )
    assert explanation is None


def test_unknown_ownership_omits_league_angle() -> None:
    practice = PracticeSignal(
        driver_number=1,
        driver_code="NOR",
        session="FP2",
        setup_sentiment=0.55,
        tire_confidence=0.65,
        mechanical_flags=[],
        pace_satisfaction=0.7,
        anomaly_flags=[],
        raw_evidence=[],
    )
    pick = _pick(driver_code="NOR", ownership_tier="UNKNOWN")
    explanation = build_explanation(
        pick,
        _ctx(practice_by_driver={"NOR": practice}, quali_grid={"NOR": 3}),
    )
    assert explanation is not None
    assert explanation.league_angle is None


def test_low_contrarian_league_angle() -> None:
    practice = PracticeSignal(
        driver_number=16,
        driver_code="LEC",
        session="FP2",
        setup_sentiment=0.6,
        tire_confidence=0.7,
        mechanical_flags=[],
        pace_satisfaction=0.7,
        anomaly_flags=[],
        raw_evidence=[],
    )
    pick = _pick(
        driver_code="LEC",
        ownership_tier="LOW",
        is_contrarian=True,
        confidence=68.0,
    )
    explanation = build_explanation(
        pick,
        _ctx(practice_by_driver={"LEC": practice}, quali_grid={"LEC": 4}),
    )
    assert explanation is not None
    assert explanation.league_angle is not None
    assert "Contrarian" in explanation.league_angle


def test_primary_signal_char_limit() -> None:
    long_text = "x" * 130
    explanation = PickExplanation(
        driver_code="NOR",
        primary_signal=long_text,
        signal_source=SignalSource.PRACTICE,
        risk_note="ok",
    )
    assert len(explanation.primary_signal) <= 120
    assert explanation.primary_signal.endswith("…")


def test_format_explanation_card_lines() -> None:
    from whatsapp.message_format import format_explanation_card

    card = format_explanation_card(
        PickExplanation(
            driver_code="NOR",
            primary_signal="FP2: setup sentiment +0.55.",
            signal_source=SignalSource.PRACTICE,
            risk_note="Limited downside at this price point.",
            league_angle="Contrarian — upside if rivals play chalk this weekend.",
        )
    )
    lines = card.split("\n")
    assert len(lines) <= 3
    assert lines[0].startswith("📊 Signal:")
    assert "⚠️" in lines[1]
