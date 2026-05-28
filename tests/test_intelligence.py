"""Unit tests for Phase 3 intelligence layer."""

from __future__ import annotations

from circuits.profiles import get_circuit_profile, load_circuit_profiles
from intelligence.context import init_orchestrator_context
from intelligence.pick_generator import generate_picks
from intelligence.schemas import PickGeneratorInput, QualifyingRow


def test_circuit_profiles_load_24() -> None:
    profiles = load_circuit_profiles()
    assert len(profiles) == 24
    monaco = get_circuit_profile("monaco")
    monza = get_circuit_profile("monza")
    assert monaco is not None and monza is not None
    assert monaco.overtaking_difficulty > monza.overtaking_difficulty
    assert monaco.positions_gained_ceiling < monza.positions_gained_ceiling


def test_generic_pick_generator() -> None:
    ctx = init_orchestrator_context()
    monaco = ctx.get_circuit("monaco")
    assert monaco is not None
    output = generate_picks(
        PickGeneratorInput(
            circuit=monaco,
            practice_signals=[],
            qualifying_result=[
                QualifyingRow(
                    driver_number=16,
                    driver_code="LEC",
                    grid_position=1,
                    session_key=1,
                )
            ],
            weather_forecast=None,
            user_team=None,
            race_key="monaco:2026",
            generated_by="rules",
        )
    )
    assert not output.personalized
    assert len(output.picks) == 3
    assert "TEAM" in output.confidence_note
