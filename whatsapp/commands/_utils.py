"""Shared helpers for WhatsApp command handlers."""

from __future__ import annotations

from dataclasses import dataclass

from circuits.profiles import get_circuit_profile
from db.models import PickRow
from fantasy.rules import DRIVER_PRICES_M, driver_price_m
from intelligence.explanation_builder import ExplanationBuildContext
from intelligence.repository import load_practice_signals_by_circuit
from intelligence.schemas import PickRecommendation
from scheduler.calendar import get_race_weekend, profile_circuit_key


def conf_bar(pct: float) -> str:
    filled = max(0, min(10, round(pct / 10)))
    return "█" * filled + "░" * (10 - filled)


def confidence_band(pct: float) -> str:
    """User-facing confidence band. Internal pct stays numeric; only display rounds."""
    if pct >= 70.0:
        return "HIGH"
    if pct >= 50.0:
        return "MED"
    return "LOW"


def accuracy_bar(pct: float) -> str:
    return conf_bar(pct)


def is_known_driver_code(token: str) -> bool:
    return token.upper() in DRIVER_PRICES_M


def pick_row_to_recommendation(row: PickRow) -> PickRecommendation:
    return PickRecommendation(
        rank=row.pick_rank,
        headline=f"Pick {row.driver_code}",
        confidence=row.confidence,
        reasoning=row.reasoning or "",
        driver_code=row.driver_code,
        predicted_points_delta=row.predicted_points_delta,
        transfer_out=row.transfer_out,
        transfer_in=row.transfer_in,
        is_contrarian=row.is_contrarian,
        ownership_tier=row.ownership_tier,
        league_strategy_applied=row.league_strategy_applied,
        opponent_conflict=row.opponent_conflict,
    )


async def explanation_context_for_race(race_key: str) -> ExplanationBuildContext:
    weekend = get_race_weekend(race_key)
    circuit_key = weekend.circuit_key if weekend else race_key.split("_", 1)[-1]
    profile_key = profile_circuit_key(circuit_key)
    practice_rows = await load_practice_signals_by_circuit(profile_key)
    practice_by_driver = {s.driver_code.upper(): s for s in practice_rows}
    return ExplanationBuildContext(
        race_key=race_key,
        circuit_key=profile_key,
        circuit=get_circuit_profile(profile_key),
        practice_by_driver=practice_by_driver,
        quali_grid={},
    )


def driver_price_line(driver_code: str) -> str:
    return f"${driver_price_m(driver_code):.1f}M"


@dataclass(frozen=True, slots=True)
class SeasonAccuracyView:
    season: int
    hit_rate_pct: float
    races_scored: int
    best_race_name: str
    best_race_pct: float
