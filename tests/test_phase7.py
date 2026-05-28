"""Phase 7 competitive value feature tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from db.models import FantasyTeam
from intelligence.chip_planner import ChipType, generate_chip_plan, remaining_races_from_now
from scheduler.calendar import CALENDAR_2026
from whatsapp.phase7 import broadcast_friday_delta


@pytest.mark.asyncio
async def test_friday_delta_skips_sprint_weekend() -> None:
    """Sprint weekends have no FP2 — Friday delta must not broadcast."""
    sprint = next(w for w in CALENDAR_2026 if w.is_sprint)
    result = await broadcast_friday_delta(sprint.race_key)
    assert result.get("skipped") == "sprint_weekend"
    assert result.get("sent") == 0


def test_chip_planner_never_recommends_used_chips() -> None:
    """Used chips must not appear in recommended_sequence."""
    team = FantasyTeam(
        phone="+10000000001",
        driver_1="VER",
        driver_2="NOR",
        driver_3="LEC",
        driver_4="PIA",
        driver_5="RUS",
        constructor_1="FER",
        constructor_2="MCL",
        remaining_budget=2.0,
        transfers_available=2,
        chips_used={"limitless": True, "wildcard": True, "no_negative": False},
        league_mode_enabled=False,
        league_size=None,
        league_strategy=None,
        opponent_profiles=[],
        updated_at=datetime.now(tz=UTC),
    )
    plan = generate_chip_plan(team, remaining_races_from_now())
    used = {k for k, v in (team.chips_used or {}).items() if v}
    for chip_name, _race_key in plan.recommended_sequence:
        assert chip_name not in used, f"recommended used chip {chip_name}"
    for window in plan.windows:
        for chip in window.recommended_chips:
            canonical = {
                ChipType.LIMITLESS: "limitless",
                ChipType.WILDCARD: "wildcard",
                ChipType.NO_NEGATIVE: "no_negative",
            }.get(chip, chip.value)
            assert canonical not in used
