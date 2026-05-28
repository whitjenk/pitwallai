"""Unit tests for constructor strategy integration in Agent 3 scoring."""

from __future__ import annotations

from agents.quali_strategist import _constructor_strategy_modifier
from circuits.profiles import get_circuit_profile
from orchestrator.race_context import ChampionshipRow, RaceContext
from scheduler.calendar import get_race_weekend


def _ctx_with_strategy() -> RaceContext:
    weekend = get_race_weekend("2026_monaco")
    circuit = get_circuit_profile("monaco")
    assert weekend is not None
    assert circuit is not None
    return RaceContext(
        race_weekend=weekend,
        circuit_profile=circuit,
        circuit_intel={
            "constructor_strategy_profiles": {
                "FER": {
                    "sample_races": 5,
                    "lead_window_samples": 4,
                    "early_pit_rate": 0.75,
                    "undercut_success_rate": 0.8,
                    "hedge_rate": 0.3,
                }
            }
        },
        built_at=weekend.race_utc,
        last_updated=weekend.race_utc,
    )


def test_constructor_strategy_modifier_positive_for_strong_profile() -> None:
    ctx = _ctx_with_strategy()
    champ = ChampionshipRow(
        driver_code="LEC",
        position=2,
        points=180.0,
        championship_pressure=0.8,
    )
    bonus, note = _constructor_strategy_modifier("LEC", ctx, champ)
    assert bonus > 0.0
    assert "FER strategy trend" in note


def test_constructor_strategy_modifier_none_for_missing_profile() -> None:
    ctx = _ctx_with_strategy()
    champ = ChampionshipRow(
        driver_code="NOR",
        position=1,
        points=200.0,
        championship_pressure=0.4,
    )
    bonus, note = _constructor_strategy_modifier("NOR", ctx, champ)
    assert bonus == 0.0
    assert note == ""
