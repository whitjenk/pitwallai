"""Unit tests for constructor strategy integration in Agent 3 scoring."""

from __future__ import annotations

from agents.quali_strategist import _constructor_pick_signal
from intelligence.constructor_strategy import ConstructorStrategyProfileData


def test_constructor_pick_signal_applies_high_quality_bonus() -> None:
    profile = ConstructorStrategyProfileData(
        constructor_code="FER",
        circuit_key="monaco",
        sample_size=6,
        early_box_rate=0.75,
        undercut_attempt_rate=0.6,
        overcut_rate=0.2,
        avg_pit_window_open_lap=0.35,
        double_stack_rate=0.1,
        safety_car_opportunist=0.7,
        championship_pressure_modifier=0.3,
        fantasy_tendency="Ferrari boxes early at Monaco — drivers often gain vs grid.",
        data_quality="HIGH",
        source_race_keys=["2024_monaco"] * 6,
    )
    signal = _constructor_pick_signal("LEC", {"FER": profile})
    assert signal.bonus > 0.0
    assert signal.tendency_note is not None
    assert "Constructor note:" in (signal.reasoning_fragment or "")


def test_constructor_pick_signal_none_for_low_quality() -> None:
    profile = ConstructorStrategyProfileData(
        constructor_code="FER",
        circuit_key="monaco",
        sample_size=2,
        early_box_rate=0.9,
        undercut_attempt_rate=0.8,
        overcut_rate=0.0,
        avg_pit_window_open_lap=0.3,
        double_stack_rate=0.0,
        safety_car_opportunist=0.9,
        championship_pressure_modifier=0.0,
        fantasy_tendency="Internal only.",
        data_quality="LOW",
        source_race_keys=["2024_monaco"],
    )
    signal = _constructor_pick_signal("LEC", {"FER": profile})
    assert signal.bonus == 0.0
    assert signal.tendency_note is None


def test_constructor_pick_signal_none_for_missing_profile() -> None:
    signal = _constructor_pick_signal("NOR", {})
    assert signal.bonus == 0.0
    assert signal.tendency_note is None
