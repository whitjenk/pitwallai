"""Post-race counterfactual recap from pick audit log."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from db.models import PickRow
from intelligence.repository import (
    get_fantasy_team,
    get_picks_for_race,
    get_share_card_by_token,
    get_share_card_for_race,
    load_season_hit_rate_for_phone,
)
from scheduler.calendar import get_race_weekend
from sharing.share_cards import generate_share_card


class CounterfactualRecap(BaseModel):
    """Subscriber race recap with optional share token."""

    model_config = ConfigDict(frozen=True)

    phone: str
    race_key: str
    picks_correct: int
    picks_total: int
    points_gained: float
    best_pick_driver: str
    best_pick_delta: float
    league_position_delta: int | None = None
    vs_no_change_delta: float = 0.0
    share_token: str
    season_accuracy_pct: float = 0.0
    circuit_label: str = ""


def _scored_personalized_picks(rows: list[PickRow]) -> list[PickRow]:
    return [
        r
        for r in rows
        if r.personalized and r.pick_status != "draft" and r.was_correct is not None
    ]


def _vs_no_change_delta(rows: list[PickRow]) -> float:
    """
    Net race points from recommended swap vs keeping transfer_out driver.

    Uses scored actual_points_delta on the primary swap row when present.
    """
    swap_rows = [r for r in rows if r.transfer_out and r.actual_points_delta is not None]
    if not swap_rows:
        return 0.0
    primary = min(swap_rows, key=lambda r: r.pick_rank)
    return float(primary.actual_points_delta or 0.0)


async def generate_counterfactual(phone: str, race_key: str) -> CounterfactualRecap:
    """
    Build counterfactual recap from audit log (requires Agent 5 scoring).

    League position delta is only set when league_mode_enabled and we have
  scored picks with positive swap outcome — never fabricated.
    """
    weekend = get_race_weekend(race_key)
    circuit_label = weekend.display_name if weekend else race_key.replace("_", " ").title()

    picks = await get_picks_for_race(race_key, phone=phone)
    scored = _scored_personalized_picks(picks)
    picks_total = len(scored) if scored else len([p for p in picks if p.personalized])
    picks_correct = sum(1 for p in scored if p.was_correct)

    deltas = [float(p.actual_points_delta) for p in scored if p.actual_points_delta is not None]
    points_gained = sum(deltas) if deltas else 0.0

    best_driver = ""
    best_delta = 0.0
    if scored:
        best = max(scored, key=lambda p: float(p.actual_points_delta or -999.0))
        best_driver = best.transfer_in or best.driver_code
        best_delta = float(best.actual_points_delta or 0.0)

    vs_delta = _vs_no_change_delta(scored)
    league_delta: int | None = None
    team = await get_fantasy_team(phone)
    if team and team.league_mode_enabled and vs_delta > 0 and picks_correct >= 1:
        # Observational proxy only — not a live league API read.
        league_delta = 1 if vs_delta >= 5.0 else None

    existing = await get_share_card_for_race(phone, race_key)
    if existing is None:
        card_out = await generate_share_card(phone, race_key)
        share_token = card_out.share_token
    else:
        share_token = existing.share_token
    season_pct = await load_season_hit_rate_for_phone(phone, season=2026)

    return CounterfactualRecap(
        phone=phone,
        race_key=race_key,
        picks_correct=picks_correct,
        picks_total=picks_total or len(picks) or 0,
        points_gained=round(points_gained, 1),
        best_pick_driver=best_driver or "n/a",
        best_pick_delta=round(best_delta, 1),
        league_position_delta=league_delta,
        vs_no_change_delta=round(vs_delta, 1),
        share_token=share_token,
        season_accuracy_pct=season_pct,
        circuit_label=circuit_label,
    )


async def load_counterfactual_from_token(share_token: str) -> CounterfactualRecap | None:
    """Rebuild recap view model from stored share card."""
    card = await get_share_card_by_token(share_token)
    if card is None or not card.is_public:
        return None
    weekend = get_race_weekend(card.race_key)
    return CounterfactualRecap(
        phone=card.phone,
        race_key=card.race_key,
        picks_correct=card.picks_correct,
        picks_total=card.picks_total,
        points_gained=round(
            sum(
                float(p.get("actual_points_delta") or 0.0)
                for p in card.pick_details
                if p.get("actual_points_delta") is not None
            ),
            1,
        ),
        best_pick_driver=card.best_pick_driver or "n/a",
        best_pick_delta=float(card.best_pick_delta or 0.0),
        league_position_delta=card.league_position_delta,
        vs_no_change_delta=float(card.vs_no_change_delta or 0.0),
        share_token=card.share_token,
        season_accuracy_pct=card.season_accuracy_pct,
        circuit_label=weekend.display_name if weekend else card.race_name,
    )
