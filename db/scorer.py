"""Public season results queries for the /results static page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC

from sqlalchemy import select

from db.models import PickRow
from db.session import get_session
from intelligence.scorer import _fetch_final_positions
from openf1.client import OpenF1Client
from circuits.profiles import get_circuit_profile
from scheduler.calendar import CALENDAR_2026, get_race_weekend, profile_circuit_key


@dataclass(frozen=True, slots=True)
class RaceResult:
    race_name: str
    round_number: int
    pick_driver: str
    actual_top_scorer: str
    fantasy_points: float
    was_correct: bool
    race_date: str


@dataclass(frozen=True, slots=True)
class SeasonAccuracy:
    """Aggregated public broadcast pick record for one season."""

    season: int
    races_scored: int
    correct_picks: int
    hit_rate_pct: float
    best_race_name: str
    best_race_pct: float
    results: list[RaceResult]


_ROUND_BY_RACE_KEY: dict[str, int] = {
    w.race_key: idx + 1 for idx, w in enumerate(CALENDAR_2026)
}


async def _race_winner_code(race_key: str, client: OpenF1Client) -> str:
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return "—"
    profile_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        return "—"
    year = int(race_key.split("_", 1)[0])
    race_sk = await client.find_session_key(
        year=year,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Race",
    )
    if race_sk is None:
        return "—"
    positions = await _fetch_final_positions(client, race_sk)
    for code, pos in positions.items():
        if pos == 1:
            return code
    return "—"


async def get_season_accuracy(season: int = 2026) -> SeasonAccuracy | None:
    """
    Fetch scored generic (broadcast) top picks for the season.

    Uses ``picks`` audit rows (``phone`` IS NULL, ``pick_rank`` = 1).
    Returns None when no races are scored or the database is unavailable.
    """
    prefix = f"{season}_"
    try:
        async with get_session() as session:
            result = await session.execute(
                select(PickRow)
                .where(
                    PickRow.race_key.like(f"{prefix}%"),
                    PickRow.phone.is_(None),
                    PickRow.pick_rank == 1,
                    PickRow.was_correct.is_not(None),
                )
                .order_by(PickRow.race_key)
            )
            rows = list(result.scalars().all())
    except ValueError:
        return None

    if not rows:
        return None

    client = OpenF1Client()
    winner_cache: dict[str, str] = {}
    results: list[RaceResult] = []

    for row in rows:
        weekend = get_race_weekend(row.race_key)
        race_name = weekend.display_name if weekend else row.race_key.replace("_", " ").title()
        race_date = (
            weekend.race_utc.astimezone(UTC).date().isoformat()
            if weekend
            else row.race_key.split("_", 1)[0] + "-01-01"
        )
        if row.race_key not in winner_cache:
            winner_cache[row.race_key] = await _race_winner_code(row.race_key, client)
        results.append(
            RaceResult(
                race_name=race_name,
                round_number=_ROUND_BY_RACE_KEY.get(row.race_key, 0),
                pick_driver=row.driver_code,
                actual_top_scorer=winner_cache[row.race_key],
                fantasy_points=float(row.actual_points_delta or 0.0),
                was_correct=bool(row.was_correct),
                race_date=race_date,
            )
        )

    results.sort(key=lambda r: (r.round_number, r.race_date))
    correct = sum(1 for r in results if r.was_correct)
    races_scored = len(results)
    hit_rate = 100.0 * correct / races_scored if races_scored else 0.0

    if correct:
        best = max(
            (r for r in results if r.was_correct),
            key=lambda r: r.fantasy_points,
        )
        best_name = best.race_name
        best_pct = 100.0
    else:
        best_name = results[0].race_name
        best_pct = 0.0

    return SeasonAccuracy(
        season=season,
        races_scored=races_scored,
        correct_picks=correct,
        hit_rate_pct=hit_rate,
        best_race_name=best_name,
        best_race_pct=best_pct,
        results=results,
    )
