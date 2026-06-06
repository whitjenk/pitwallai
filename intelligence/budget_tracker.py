"""Team value and effective budget tracking."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from fantasy.rules import (
    BUDGET_CAP_M,
    constructor_price_m,
    driver_price_m,
)
from intelligence.repository import get_fantasy_team, upsert_team_value_snapshot
from scheduler.calendar import CALENDAR_2026


class TeamValueSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    phone: str
    race_key: str
    team_value: float
    value_delta: float
    effective_budget: float
    updated_at: datetime


def _team_codes(team) -> tuple[list[str], list[str]]:
    drivers = [
        c
        for c in (
            team.driver_1,
            team.driver_2,
            team.driver_3,
            team.driver_4,
            team.driver_5,
        )
        if c
    ]
    constructors = [c for c in (team.constructor_1, team.constructor_2) if c]
    return drivers, constructors


def compute_team_value(drivers: list[str], constructors: list[str]) -> float:
    total = sum(driver_price_m(c) for c in drivers)
    total += sum(constructor_price_m(c) for c in constructors)
    return round(total, 2)


async def track_team_value(phone: str, race_key: str) -> TeamValueSnapshot:
    """Snapshot squad value vs $100M cap baseline."""
    team = await get_fantasy_team(phone)
    if team is None:
        raise ValueError("No fantasy team")
    drivers, constructors = _team_codes(team)
    value = compute_team_value(drivers, constructors)
    effective = round(value - BUDGET_CAP_M, 2)

    prior_key = _prior_race_key(race_key)
    prior_value = value
    if prior_key:
        from intelligence.repository import get_session
        from sqlalchemy import select

        async with get_session() as session:
            from db.models import TeamValueSnapshot as TVRow

            result = await session.execute(
                select(TVRow).where(TVRow.phone == phone, TVRow.race_key == prior_key)
            )
            row = result.scalars().first()
            if row:
                prior_value = float(row.team_value)

    delta = round(value - prior_value, 2)
    snap = TeamValueSnapshot(
        phone=phone,
        race_key=race_key,
        team_value=value,
        value_delta=delta,
        effective_budget=effective,
        updated_at=datetime.now(tz=UTC),
    )
    await upsert_team_value_snapshot(
        phone=phone,
        race_key=race_key,
        team_value=value,
        value_delta=delta,
        effective_budget=effective,
    )
    return snap


def _prior_race_key(race_key: str) -> str | None:
    keys = [w.race_key for w in CALENDAR_2026]
    if race_key not in keys:
        return None
    idx = keys.index(race_key)
    if idx <= 0:
        return None
    return keys[idx - 1]


def format_budget_whatsapp(snap: TeamValueSnapshot, *, cash_remaining: float | None = None) -> str:
    lines = [f"💰 Team value: ${snap.team_value:.1f}M ({snap.value_delta:+.1f}M this race)"]
    # Value above the $100M cap is appreciation you bank when you sell — it is
    # NOT spendable cash. Spendable budget for a transfer is your cash in hand
    # plus whatever you free up by dropping a driver.
    if snap.effective_budget > 0:
        lines.append(f"Appreciation: +${snap.effective_budget:.1f}M above the $100M cap")
    # Transfer affordability is driven by cash in hand, not appreciation.
    if cash_remaining is not None:
        lines.append(f"Cash in hand: ${cash_remaining:.1f}M (plus the sale price of any driver you drop)")
        if cash_remaining >= 3.0:
            lines.append("Good headroom — you can reach for a pricier swap.")
        elif cash_remaining < 0.5:
            lines.append("Tight on cash — swaps must be roughly price-neutral.")
    text = "\n".join(lines)
    if len(text) > 280:
        return text[:277] + "..."
    return text
