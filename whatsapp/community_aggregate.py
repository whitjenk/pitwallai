"""Post-race community aggregate WhatsApp broadcast (read-only reporting)."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy import case, func, select

from db.models import FantasyTeam, PickRow, ShareCard
from db.session import get_session
from intelligence.repository import load_season_accuracy_row
from scheduler.calendar import CALENDAR_2026, get_race_weekend
from whatsapp.broadcast import send_to_all_active

_MIN_PICKS = 10
_MIN_OWNERSHIP_GROUP = 5
_MIN_ATTACK_SUBSCRIBERS = 3
_MAX_MESSAGE_CHARS = 380

_SENT_PICK_FILTER = PickRow.pick_status != "draft"


@dataclass(frozen=True, slots=True)
class CommunityAggregateStats:
    """Computed community metrics for one race weekend."""

    race_name: str
    total_picks_sent: int
    correct_picks_pct: float
    personalized_count: int
    generic_count: int
    contrarian_avg_delta: float | None
    consensus_avg_delta: float | None
    contrarian_count: int
    consensus_count: int
    attack_mode_avg_gain: float | None
    best_driver_code: str | None
    season_races_scored: int
    season_overall_accuracy: float
    skip_ownership_comparison: bool


async def load_community_aggregate_stats(race_key: str) -> CommunityAggregateStats | None:
    """
    Load aggregate metrics via SQL (read-only).

    Returns None if race_key is unknown.
    """
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return None

    season_races_scored = sum(
        1 for w in CALENDAR_2026 if w.race_utc <= weekend.race_utc
    )
    season_row = await load_season_accuracy_row(2026)
    season_accuracy = float(season_row.overall_accuracy) if season_row else 0.0

    async with get_session() as session:
        base = await session.execute(
            select(
                func.count(PickRow.id),
                func.sum(case((PickRow.personalized.is_(True), 1), else_=0)),
                func.sum(case((PickRow.personalized.is_(False), 1), else_=0)),
                func.sum(case((PickRow.was_correct.is_(True), 1), else_=0)),
                func.sum(case((PickRow.was_correct.is_not(None), 1), else_=0)),
            ).where(PickRow.race_key == race_key, _SENT_PICK_FILTER)
        )
        total, pers, generic, correct, scored = base.one()

        total_picks = int(total or 0)
        personalized_count = int(pers or 0)
        generic_count = int(generic or 0)
        scored_count = int(scored or 0)
        if scored_count > 0:
            correct_picks_pct = 100.0 * int(correct or 0) / scored_count
        else:
            correct_picks_pct = 0.0

        low_tier = func.upper(PickRow.ownership_tier) == "LOW"
        high_tier = func.upper(PickRow.ownership_tier) == "HIGH"
        delta_ok = PickRow.actual_points_delta.is_not(None)

        contra_row = await session.execute(
            select(
                func.count(PickRow.id),
                func.avg(PickRow.actual_points_delta),
            ).where(
                PickRow.race_key == race_key,
                _SENT_PICK_FILTER,
                low_tier,
                delta_ok,
            )
        )
        cons_row = await session.execute(
            select(
                func.count(PickRow.id),
                func.avg(PickRow.actual_points_delta),
            ).where(
                PickRow.race_key == race_key,
                _SENT_PICK_FILTER,
                high_tier,
                delta_ok,
            )
        )
        contra_count, contra_avg = contra_row.one()
        cons_count, cons_avg = cons_row.one()
        contrarian_count = int(contra_count or 0)
        consensus_count = int(cons_count or 0)
        contrarian_avg_delta = (
            float(contra_avg) if contrarian_count >= _MIN_OWNERSHIP_GROUP and contra_avg is not None else None
        )
        consensus_avg_delta = (
            float(cons_avg) if consensus_count >= _MIN_OWNERSHIP_GROUP and cons_avg is not None else None
        )

        best_row = await session.execute(
            select(
                PickRow.driver_code,
                func.count(PickRow.id).label("hits"),
                func.avg(PickRow.confidence).label("avg_conf"),
            )
            .where(
                PickRow.race_key == race_key,
                _SENT_PICK_FILTER,
                PickRow.was_correct.is_(True),
            )
            .group_by(PickRow.driver_code)
            .order_by(func.count(PickRow.id).desc(), func.avg(PickRow.confidence).desc())
            .limit(1)
        )
        best = best_row.first()
        best_driver_code = best.driver_code if best else None

        attack_strategy = func.upper(FantasyTeam.league_strategy) == "ATTACK"
        attack_count_row = await session.execute(
            select(func.count(func.distinct(ShareCard.phone)))
            .select_from(ShareCard)
            .join(FantasyTeam, ShareCard.phone == FantasyTeam.phone)
            .where(
                ShareCard.race_key == race_key,
                FantasyTeam.league_mode_enabled.is_(True),
                attack_strategy,
                ShareCard.league_position_delta.is_not(None),
            )
        )
        attack_subscriber_count = int(attack_count_row.scalar() or 0)

        attack_avg_row = await session.execute(
            select(func.avg(ShareCard.league_position_delta))
            .select_from(ShareCard)
            .join(FantasyTeam, ShareCard.phone == FantasyTeam.phone)
            .where(
                ShareCard.race_key == race_key,
                FantasyTeam.league_mode_enabled.is_(True),
                attack_strategy,
                ShareCard.league_position_delta.is_not(None),
            )
        )
        attack_avg = attack_avg_row.scalar()
        attack_mode_avg_gain = (
            float(attack_avg)
            if attack_subscriber_count >= _MIN_ATTACK_SUBSCRIBERS and attack_avg is not None
            else None
        )

    return CommunityAggregateStats(
        race_name=weekend.display_name,
        total_picks_sent=total_picks,
        correct_picks_pct=round(correct_picks_pct, 1),
        personalized_count=personalized_count,
        generic_count=generic_count,
        contrarian_avg_delta=contrarian_avg_delta,
        consensus_avg_delta=consensus_avg_delta,
        contrarian_count=contrarian_count,
        consensus_count=consensus_count,
        attack_mode_avg_gain=attack_mode_avg_gain,
        best_driver_code=best_driver_code,
        season_races_scored=season_races_scored,
        season_overall_accuracy=round(season_accuracy, 1),
        skip_ownership_comparison=season_races_scored <= 1,
    )


def format_community_aggregate_message(stats: CommunityAggregateStats) -> str:
    """
    Assemble sections with sample gates; enforce 380-char limit.

    Sections 1 and 5 are never dropped.
    """
    s1 = (
        f"📊 {stats.race_name} community results\n\n"
        f"{stats.correct_picks_pct:.0f}% of PitWallAI picks scored this weekend"
    )

    s2: str | None = None
    if (
        not stats.skip_ownership_comparison
        and stats.contrarian_avg_delta is not None
        and stats.consensus_avg_delta is not None
        and stats.contrarian_avg_delta != stats.consensus_avg_delta
    ):
        if stats.contrarian_avg_delta > stats.consensus_avg_delta:
            s2 = (
                f"\nContrarian picks: +{stats.contrarian_avg_delta:.1f}pts avg "
                f"vs consensus +{stats.consensus_avg_delta:.1f}pts avg"
            )
        else:
            s2 = "\nConsensus picks led this weekend"

    s3: str | None = None
    if stats.attack_mode_avg_gain is not None:
        n = stats.attack_mode_avg_gain
        pos_label = "position" if abs(n - 1.0) < 0.01 else "positions"
        sign = "+" if n >= 0 else ""
        s3 = f"\nATTACK mode: avg {sign}{n:.0f} league {pos_label} gained"

    s4: str | None = None
    if stats.best_driver_code:
        s4 = f"\n🏆 Best call: {stats.best_driver_code}"

    s5 = (
        f"\n\nSeason: {stats.season_races_scored} races · "
        f"{stats.season_overall_accuracy:.0f}% accuracy\n"
        "pitwallai.app/accuracy"
    )

    optional: list[str | None] = [s2, s3, s4]
    while True:
        sections = [s1] + [s for s in optional if s] + [s5]
        message = "".join(sections)
        if len(message) <= _MAX_MESSAGE_CHARS:
            break
        if optional[2]:
            optional[2] = None
        elif optional[1]:
            optional[1] = None
        elif optional[0]:
            optional[0] = None
        else:
            break

    assert len(message) <= _MAX_MESSAGE_CHARS, (
        f"community aggregate message {len(message)} chars exceeds {_MAX_MESSAGE_CHARS}"
    )
    return message


async def broadcast_community_aggregate(race_key: str) -> dict[str, int | str]:
    """
    Compute community stats and broadcast to all active subscribers.

    Minimum 10 picks required. Subscriber count checked by scheduler job.
    """
    stats = await load_community_aggregate_stats(race_key)
    if stats is None:
        logger.warning("community_aggregate: unknown race_key={}", race_key)
        return {"sent": 0, "skipped": "unknown_race"}

    if stats.total_picks_sent < _MIN_PICKS:
        logger.warning(
            "community_aggregate skipped race_key={}: only {} picks (need {})",
            race_key,
            stats.total_picks_sent,
            _MIN_PICKS,
        )
        return {"sent": 0, "skipped": "insufficient_picks"}

    message = format_community_aggregate_message(stats)
    result = await send_to_all_active(message)
    logger.bind(
        race_key=race_key,
        picks=stats.total_picks_sent,
        correct_pct=stats.correct_picks_pct,
    ).info("community_aggregate broadcast complete")
    return result
