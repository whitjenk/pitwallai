"""Weekly share card generation for post-race viral loop."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from db.models import PickRow, ShareCard
from db.session import get_session
from intelligence.repository import (
    get_fantasy_team,
    get_picks_for_race,
    get_subscriber,
    load_season_hit_rate_for_phone,
)
from scheduler.calendar import get_race_weekend
from sqlalchemy import select


class ShareCardOut(BaseModel):
    """Public share card payload."""

    model_config = ConfigDict(frozen=True)

    share_token: str
    phone: str
    race_key: str
    race_name: str
    circuit_key: str
    picks_correct: int
    picks_total: int
    accuracy_pct: float
    season_accuracy_pct: float
    best_pick_driver: str | None = None
    best_pick_delta: float | None = None
    league_position_delta: int | None = None
    is_public: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))


def _pick_detail_rows(rows: list[PickRow]) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        if row.pick_status == "draft":
            continue
        out.append(
            {
                "driver_code": row.driver_code,
                "transfer_out": row.transfer_out,
                "transfer_in": row.transfer_in,
                "reasoning": (row.reasoning or "")[:200],
                "was_correct": row.was_correct,
                "actual_points_delta": row.actual_points_delta,
                "confidence": row.confidence,
            }
        )
    return out


async def generate_share_card(phone: str, race_key: str) -> ShareCardOut:
    """Create or refresh share card after race scoring."""
    weekend = get_race_weekend(race_key)
    if weekend is None:
        raise ValueError(f"Unknown race_key: {race_key}")

    picks = await get_picks_for_race(race_key, phone=phone)
    sent = [p for p in picks if p.pick_status != "draft" and p.was_correct is not None]
    personalized = [p for p in sent if p.personalized] or sent
    picks_total = len(personalized) if personalized else 0
    picks_correct = sum(1 for p in personalized if p.was_correct)

    accuracy = (100.0 * picks_correct / picks_total) if picks_total else 0.0
    season_pct = await load_season_hit_rate_for_phone(phone, season=2026)

    best_driver: str | None = None
    best_delta: float | None = None
    scored_deltas = [p for p in personalized if p.actual_points_delta is not None]
    if scored_deltas:
        best = max(scored_deltas, key=lambda p: float(p.actual_points_delta or -999.0))
        best_driver = best.transfer_in or best.driver_code
        best_delta = float(best.actual_points_delta or 0.0)

    vs_delta = 0.0
    swap_rows = [p for p in personalized if p.transfer_out and p.actual_points_delta is not None]
    if swap_rows:
        vs_delta = float(min(swap_rows, key=lambda r: r.pick_rank).actual_points_delta or 0.0)

    sub = await get_subscriber(phone)
    is_public = not (sub.share_cards_private if sub else False)

    token = str(uuid.uuid4())
    async with get_session() as session:
        session.add(
            ShareCard(
                share_token=token,
                phone=phone,
                race_key=race_key,
                race_name=weekend.display_name,
                circuit_key=weekend.circuit_key,
                picks_correct=picks_correct,
                picks_total=picks_total,
                accuracy_pct=round(accuracy, 1),
                season_accuracy_pct=round(season_pct, 1),
                best_pick_driver=best_driver,
                best_pick_delta=best_delta,
                league_position_delta=None,
                vs_no_change_delta=vs_delta,
                pick_details=_pick_detail_rows(personalized),
                is_public=is_public,
            )
        )
        await session.flush()

    return ShareCardOut(
        share_token=token,
        phone=phone,
        race_key=race_key,
        race_name=weekend.display_name,
        circuit_key=weekend.circuit_key,
        picks_correct=picks_correct,
        picks_total=picks_total,
        accuracy_pct=round(accuracy, 1),
        season_accuracy_pct=round(season_pct, 1),
        best_pick_driver=best_driver,
        best_pick_delta=best_delta,
        is_public=is_public,
    )
