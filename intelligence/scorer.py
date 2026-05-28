"""Post-race scoring and recap broadcast."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from db.models import PickRow, Subscriber
from intelligence.drivers import driver_code_for
from intelligence.repository import (
    get_all_picks_for_race,
    get_fantasy_team,
    get_picks_for_race,
    list_subscribers_for_race_picks,
    upsert_season_accuracy,
)
from openf1.client import OpenF1Client
from scheduler.calendar import get_next_race_weekend, get_race_weekend
from whatsapp.message_format import format_recap_message
from whatsapp.sender import mask_phone, send_message

from fantasy.rules import driver_points_race as _official_race_points


@dataclass(frozen=True, slots=True)
class SeasonStats:
    """Aggregated season accuracy metrics."""

    season: int
    overall_accuracy: float
    personalized_accuracy: float
    generic_accuracy: float
    best_circuit: str
    worst_circuit: str


def _points_for_position(position: int | None) -> float:
    """Official F1 Fantasy Grand Prix points (P1–P10, DNF/NC = -20)."""
    if position is None:
        return float(_official_race_points(None, classified=False))
    return float(_official_race_points(position, classified=position <= 20))


async def _fetch_final_positions(client: OpenF1Client, session_key: int) -> dict[str, int]:
    """
    Final classified positions from the last position sample per driver.

    Returns:
        driver_code → finishing position (1 = winner).
    """
    samples = await client.get_positions(session_key)
    latest: dict[int, tuple[datetime | None, int]] = {}
    for sample in samples:
        if sample.position is None:
            continue
        prior = latest.get(sample.driver_number)
        sample_date = sample.date or datetime.min.replace(tzinfo=UTC)
        if prior is None or (prior[0] or datetime.min.replace(tzinfo=UTC)) <= sample_date:
            latest[sample.driver_number] = (sample.date, sample.position)

    return {
        driver_code_for(num): pos for num, (_, pos) in latest.items()
    }


def _score_personalized_pick(
    pick: PickRow,
    positions: dict[str, int],
) -> tuple[float, bool]:
    """Points delta for swap recommendation vs keeping transfer_out driver."""
    in_code = pick.transfer_in or pick.driver_code
    out_code = pick.transfer_out
    in_pts = _points_for_position(positions.get(in_code))
    if out_code:
        out_pts = _points_for_position(positions.get(out_code))
        delta = in_pts - out_pts
        return delta, delta > 0
    finished_points = positions.get(in_code, 99) <= 10
    return in_pts, finished_points


def _score_generic_pick(pick: PickRow, positions: dict[str, int]) -> tuple[float, bool]:
    """Generic pick correct if driver finished in the points (top 10)."""
    pos = positions.get(pick.driver_code)
    pts = _points_for_position(pos)
    correct = pos is not None and pos <= 10
    return pts, correct


def _session_quality_note(picks: list[PickRow]) -> str | None:
    """Compact weekend scorecard for PitWallAI model quality."""
    if not picks:
        return None
    total = len(picks)
    correct = sum(1 for p in picks if p.was_correct)
    scored = [float(p.actual_points_delta) for p in picks if p.actual_points_delta is not None]
    avg_delta = (sum(scored) / len(scored)) if scored else 0.0
    sign = "+" if avg_delta >= 0 else ""
    return f"PitWallAI session: {int(round(100 * correct / total))}% hit · {sign}{avg_delta:.1f} avg pts"


async def score_race(race_key: str) -> SeasonStats:
    """
    Score all picks for a race and update season accuracy.

    Args:
        race_key: Calendar race key (e.g. 2026_monaco).

    Returns:
        Updated season statistics.
    """
    weekend = get_race_weekend(race_key)
    if weekend is None:
        raise ValueError(f"Unknown race_key: {race_key}")

    from circuits.profiles import get_circuit_profile
    from scheduler.calendar import profile_circuit_key

    profile_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        raise ValueError(f"No circuit profile for {profile_key}")

    client = OpenF1Client()
    race_sk = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Race",
    )
    if race_sk is None:
        raise ValueError(f"Race session not found for {weekend.display_name}")

    positions = await _fetch_final_positions(client, race_sk)
    picks = await get_all_picks_for_race(race_key)

    from intelligence.repository import update_pick_result

    for pick in picks:
        if pick.personalized:
            delta, correct = _score_personalized_pick(pick, positions)
        else:
            delta, correct = _score_generic_pick(pick, positions)
        await update_pick_result(pick.id, actual_points_delta=delta, was_correct=correct)

    season = 2026
    stats = await _compute_season_stats(season)
    await upsert_season_accuracy(
        season=season,
        overall_accuracy=stats.overall_accuracy,
        personalized_accuracy=stats.personalized_accuracy,
        generic_accuracy=stats.generic_accuracy,
        best_circuit=stats.best_circuit,
        worst_circuit=stats.worst_circuit,
    )

    logger.bind(
        race_key=race_key,
        picks=len(picks),
        overall=stats.overall_accuracy,
    ).info("score_race complete")

    return stats


async def _compute_season_stats(season: int) -> SeasonStats:
    """Aggregate accuracy from all scored picks in a season."""
    from sqlalchemy import select

    from db.models import PickRow
    from db.session import get_session

    prefix = f"{season}_"
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{prefix}%"),
                PickRow.was_correct.is_not(None),
            )
        )
        rows = list(result.scalars().all())

    if not rows:
        return SeasonStats(season, 0.0, 0.0, 0.0, "n/a", "n/a")

    def _accuracy(subset: list[PickRow]) -> float:
        if not subset:
            return 0.0
        return 100.0 * sum(1 for r in subset if r.was_correct) / len(subset)

    overall = _accuracy(rows)
    personalized = _accuracy([r for r in rows if r.personalized])
    generic = _accuracy([r for r in rows if not r.personalized])

    by_circuit: dict[str, list[PickRow]] = defaultdict(list)
    for row in rows:
        by_circuit[row.circuit_key].append(row)

    circuit_acc = {
        ck: _accuracy(ps) for ck, ps in by_circuit.items() if ps
    }
    best = max(circuit_acc, key=circuit_acc.get) if circuit_acc else "n/a"
    worst = min(circuit_acc, key=circuit_acc.get) if circuit_acc else "n/a"

    return SeasonStats(
        season=season,
        overall_accuracy=overall,
        personalized_accuracy=personalized,
        generic_accuracy=generic,
        best_circuit=best,
        worst_circuit=worst,
    )


async def broadcast_race_recap(race_key: str) -> dict[str, Any]:
    """
    Send post-race recap to subscribers who received picks for this race.

    Neutral tone — no mockery when all picks were wrong.
    """
    weekend = get_race_weekend(race_key)
    if weekend is None:
        raise ValueError(f"Unknown race_key: {race_key}")

    subscribers = await list_subscribers_for_race_picks(race_key)
    if not subscribers:
        logger.warning("broadcast_race_recap: no subscribers for race_key={}", race_key)
        return {"race_key": race_key, "sent": 0}

    stats = await _compute_season_stats(2026)
    next_weekend = get_next_race_weekend(after=weekend.race_utc)
    days_until: int | None = None
    next_name: str | None = None
    if next_weekend is not None:
        next_name = next_weekend.display_name
        days_until = max(0, (next_weekend.race_utc - datetime.now(tz=UTC)).days)

    sent = 0
    failed = 0

    for sub in subscribers:
        try:
            message = await _build_recap_for_subscriber(
                sub,
                race_key=race_key,
                weekend_display=weekend.display_name,
                season_accuracy=stats.overall_accuracy,
                next_race_name=next_name,
                days_until_next=days_until,
            )
            await send_message(sub.phone, message)
            sent += 1
            logger.bind(phone=mask_phone(sub.phone), race_key=race_key).info("Recap sent")
        except Exception as exc:
            failed += 1
            logger.error(
                "Recap failed phone={} race_key={}: {}",
                mask_phone(sub.phone),
                race_key,
                exc,
            )

    return {"race_key": race_key, "sent": sent, "failed": failed}


async def _build_recap_for_subscriber(
    sub: Subscriber,
    *,
    race_key: str,
    weekend_display: str,
    season_accuracy: float,
    next_race_name: str | None,
    days_until_next: int | None,
) -> str:
    picks = await get_picks_for_race(race_key, phone=sub.phone)
    if not picks:
        picks = await get_picks_for_race(race_key, phone=None)

    correct = sum(1 for p in picks if p.was_correct)
    total = len(picks)

    swap_note: str | None = None
    team = await get_fantasy_team(sub.phone)
    personalized_rows = [p for p in picks if p.personalized and p.phone == sub.phone]

    if personalized_rows and correct > 0:
        best = personalized_rows[0]
        if best.actual_points_delta is not None and best.actual_points_delta > 0:
            swap_note = f"Best swap netted +{int(best.actual_points_delta)} pts"
    elif personalized_rows and correct == 0:
        best = personalized_rows[0]
        if best.actual_points_delta is not None and best.actual_points_delta < 0:
            swap_note = (
                f"Suggested swap would have lost {int(abs(best.actual_points_delta))} pts"
            )

    nudge = team is None or team.remaining_budget is None

    return format_recap_message(
        circuit_name=weekend_display,
        correct_count=correct,
        total_picks=total if total > 0 else 3,
        season_accuracy_pct=season_accuracy,
        session_note=_session_quality_note(picks),
        swap_note=swap_note,
        next_race_name=next_race_name,
        days_until_next=days_until_next,
        nudge_team=nudge,
    )
