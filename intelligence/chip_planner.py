"""Season chip window planner (observational, not directive)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from circuits.profiles import CircuitProfile, get_circuit_profile
from db.models import FantasyTeam
from fantasy.rules import CHIP_NAMES_2026, chip_available, normalize_chip_name
from intelligence.repository import get_chip_plan_by_token, save_chip_plan
from scheduler.calendar import CALENDAR_2026, RaceWeekend, get_race_weekend, profile_circuit_key


class ChipType(str, Enum):
    WILDCARD = "wildcard"
    LIMITLESS = "limitless"
    NO_NEGATIVE = "no_negative"
    EXTRA_DRS = "3x_boost"
    FINAL_FIX = "final_fix"
    AUTOPILOT = "autopilot"


CHIP_TO_CANONICAL: dict[ChipType, str] = {
    ChipType.WILDCARD: "wildcard",
    ChipType.LIMITLESS: "limitless",
    ChipType.NO_NEGATIVE: "no_negative",
    ChipType.EXTRA_DRS: "3x_boost",
    ChipType.FINAL_FIX: "final_fix",
    ChipType.AUTOPILOT: "autopilot",
}


class ChipWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    race_key: str
    circuit_key: str
    race_name: str
    race_utc: datetime
    is_sprint: bool
    championship_week: int
    recommended_chips: list[ChipType] = Field(default_factory=list)
    reasoning: str
    confidence: float
    priority: str


class ChipPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    windows: list[ChipWindow]
    recommended_sequence: list[tuple[str, str]]
    sprint_warnings: list[str]
    mini_league_windows: list[str]
    generated_at: datetime
    share_token: str = ""


def _chips_used_set(team: FantasyTeam) -> set[str]:
    used: set[str] = set()
    for key, val in (team.chips_used or {}).items():
        if val:
            canonical = normalize_chip_name(key) or key
            used.add(canonical)
    return used


def _available_chip_types(team: FantasyTeam) -> list[ChipType]:
    used = _chips_used_set(team)
    out: list[ChipType] = []
    for chip in ChipType:
        canonical = CHIP_TO_CANONICAL[chip]
        if canonical in CHIP_NAMES_2026 and chip_available(team.chips_used or {}, canonical):
            if canonical not in used:
                out.append(chip)
    return out


def _score_window(
    weekend: RaceWeekend,
    circuit: CircuitProfile,
    *,
    pressure_avg: float,
) -> tuple[float, list[ChipType], str]:
    base = (
        circuit.tire_deg_rate * 0.3
        + circuit.safety_car_probability * 0.2
        + circuit.weather_sensitivity * 0.2
        + pressure_avg * 0.3
    )
    rec: list[ChipType] = []
    reasons: list[str] = []

    limitless_mod = 0.0
    if circuit.overtaking_difficulty > 0.55:
        limitless_mod += 0.4
        reasons.append("high overtaking difficulty")
    if circuit.weather_sensitivity > 0.7:
        limitless_mod += 0.3
        reasons.append("weather-sensitive circuit")
    if weekend.is_sprint:
        limitless_mod += 0.2
        reasons.append("sprint weekend")

    no_neg_mod = 0.0
    if circuit.weather_sensitivity > 0.8:
        no_neg_mod += 0.5
    if circuit.safety_car_probability > 0.6:
        no_neg_mod += 0.3

    wildcard_mod = 0.3 if circuit.tire_deg_rate > 0.65 else 0.1

    scores = {
        ChipType.LIMITLESS: base + limitless_mod,
        ChipType.NO_NEGATIVE: base + no_neg_mod,
        ChipType.WILDCARD: base + wildcard_mod,
        ChipType.EXTRA_DRS: base + 0.15,
        ChipType.FINAL_FIX: base + 0.1,
        ChipType.AUTOPILOT: base + 0.05,
    }
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for chip, sc in ranked[:2]:
        if sc > 0.45:
            rec.append(chip)
    priority = "HIGH" if ranked[0][1] > 0.75 else "MEDIUM" if ranked[0][1] > 0.55 else "LOW"
    reasoning = "; ".join(reasons[:2]) or f"base circuit score {base:.2f}"
    return ranked[0][1], rec, reasoning


def generate_chip_plan(
    fantasy_team: FantasyTeam,
    remaining_races: list[RaceWeekend],
) -> ChipPlan:
    """Score remaining races for chip windows; never recommend used chips."""
    available = _available_chip_types(fantasy_team)
    used = _chips_used_set(fantasy_team)
    pressure_avg = 0.5
    windows: list[ChipWindow] = []
    now = datetime.now(tz=UTC)
    upcoming = [w for w in remaining_races if w.race_utc > now]

    for idx, weekend in enumerate(upcoming, start=1):
        profile = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
        if profile is None:
            continue
        score, rec, reasoning = _score_window(weekend, profile, pressure_avg=pressure_avg)
        rec = [c for c in rec if c in available and CHIP_TO_CANONICAL[c] not in used]
        windows.append(
            ChipWindow(
                race_key=weekend.race_key,
                circuit_key=weekend.circuit_key,
                race_name=weekend.display_name,
                race_utc=weekend.race_utc,
                is_sprint=weekend.is_sprint,
                championship_week=idx,
                recommended_chips=rec,
                reasoning=reasoning,
                confidence=round(min(0.95, score), 2),
                priority="HIGH" if score > 0.75 else "MEDIUM" if score > 0.55 else "LOW",
            )
        )

    sequence: list[tuple[str, str]] = []
    assigned: set[ChipType] = set()
    for window in sorted(windows, key=lambda w: w.confidence, reverse=True):
        for chip in window.recommended_chips:
            if chip in assigned or chip not in available:
                continue
            sequence.append((chip.value, window.race_key))
            assigned.add(chip)
            if len(sequence) >= len(available):
                break

    sprint_warnings: list[str] = []
    if chip_available(fantasy_team.chips_used or {}, "limitless"):
        for w in upcoming:
            if w.is_sprint:
                sprint_warnings.append(
                    f"Sprint weekend at {w.display_name} — Limitless can score on sprint "
                    "and race if your drivers are strong there."
                )
                break

    mini_league: list[str] = []
    if fantasy_team.league_size and fantasy_team.league_mode_enabled:
        mini_league.append(
            f"Mini-league size ~{fantasy_team.league_size}: chip timing may matter more in tight tables."
        )

    token = str(uuid.uuid4())
    plan = ChipPlan(
        windows=windows,
        recommended_sequence=sequence,
        sprint_warnings=sprint_warnings,
        mini_league_windows=mini_league,
        generated_at=datetime.now(tz=UTC),
        share_token=token,
    )
    return plan


async def persist_chip_plan(phone: str, plan: ChipPlan) -> ChipPlan:
    await save_chip_plan(
        phone,
        plan.share_token,
        plan.model_dump(mode="json"),
    )
    return plan


async def load_chip_plan(share_token: str) -> ChipPlan | None:
    row = await get_chip_plan_by_token(share_token)
    if row is None:
        return None
    return ChipPlan.model_validate(row.plan_json)


def remaining_races_from_now() -> list[RaceWeekend]:
    now = datetime.now(tz=UTC)
    return [w for w in CALENDAR_2026 if w.race_utc > now]
