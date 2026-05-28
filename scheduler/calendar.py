"""
2026 F1 race calendar — all times stored in UTC.

Bahrain and Saudi Arabian Grands Prix are omitted (cancelled for 2026).
Madrid uses circuit_key ``madrid`` (profile fallback to Barcelona in jobs).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class RaceWeekend:
    """Single Grand Prix weekend with UTC session schedule."""

    race_key: str
    circuit_key: str
    display_name: str
    fp1_utc: datetime
    fp2_utc: datetime
    fp3_utc: datetime
    qualifying_utc: datetime
    race_utc: datetime
    fantasy_lock_utc: datetime


def _race(
    circuit_key: str,
    display_name: str,
    *,
    year: int,
    race_utc: datetime,
) -> RaceWeekend:
    """
    Build a RaceWeekend from race start (UTC).

    FP1/FP2 on Friday, FP3 + Qualifying on Saturday, fantasy lock 1hr before race.
    """
    race = race_utc.replace(tzinfo=UTC) if race_utc.tzinfo is None else race_utc
    friday = race.date() - timedelta(days=2)
    saturday = race.date() - timedelta(days=1)
    fp1 = datetime(friday.year, friday.month, friday.day, 11, 0, tzinfo=UTC)
    fp2 = datetime(friday.year, friday.month, friday.day, 15, 0, tzinfo=UTC)
    fp3 = datetime(saturday.year, saturday.month, saturday.day, 11, 0, tzinfo=UTC)
    qualifying = datetime(saturday.year, saturday.month, saturday.day, 14, 0, tzinfo=UTC)
    fantasy_lock = race - timedelta(hours=1)
    return RaceWeekend(
        race_key=f"{year}_{circuit_key}",
        circuit_key=circuit_key,
        display_name=display_name,
        fp1_utc=fp1,
        fp2_utc=fp2,
        fp3_utc=fp3,
        qualifying_utc=qualifying,
        race_utc=race,
        fantasy_lock_utc=fantasy_lock,
    )


# 2026 confirmed calendar (22 rounds) — race start times approximate UTC
CALENDAR_2026: tuple[RaceWeekend, ...] = (
    _race("melbourne", "Australian Grand Prix", year=2026, race_utc=datetime(2026, 3, 8, 5, 0, tzinfo=UTC)),
    _race("shanghai", "Chinese Grand Prix", year=2026, race_utc=datetime(2026, 3, 15, 7, 0, tzinfo=UTC)),
    _race("suzuka", "Japanese Grand Prix", year=2026, race_utc=datetime(2026, 3, 29, 5, 0, tzinfo=UTC)),
    _race("miami", "Miami Grand Prix", year=2026, race_utc=datetime(2026, 5, 3, 20, 0, tzinfo=UTC)),
    _race("montreal", "Canadian Grand Prix", year=2026, race_utc=datetime(2026, 5, 24, 18, 0, tzinfo=UTC)),
    _race("monaco", "Monaco Grand Prix", year=2026, race_utc=datetime(2026, 6, 7, 13, 0, tzinfo=UTC)),
    _race("barcelona", "Barcelona-Catalunya Grand Prix", year=2026, race_utc=datetime(2026, 6, 14, 13, 0, tzinfo=UTC)),
    _race("spielberg", "Austrian Grand Prix", year=2026, race_utc=datetime(2026, 6, 28, 13, 0, tzinfo=UTC)),
    _race("silverstone", "British Grand Prix", year=2026, race_utc=datetime(2026, 7, 5, 14, 0, tzinfo=UTC)),
    _race("spa", "Belgian Grand Prix", year=2026, race_utc=datetime(2026, 7, 19, 13, 0, tzinfo=UTC)),
    _race("hungaroring", "Hungarian Grand Prix", year=2026, race_utc=datetime(2026, 7, 26, 13, 0, tzinfo=UTC)),
    _race("zandvoort", "Dutch Grand Prix", year=2026, race_utc=datetime(2026, 8, 23, 13, 0, tzinfo=UTC)),
    _race("monza", "Italian Grand Prix", year=2026, race_utc=datetime(2026, 9, 6, 13, 0, tzinfo=UTC)),
    _race("madrid", "Madrid Grand Prix", year=2026, race_utc=datetime(2026, 9, 13, 13, 0, tzinfo=UTC)),
    _race("baku", "Azerbaijan Grand Prix", year=2026, race_utc=datetime(2026, 9, 26, 12, 0, tzinfo=UTC)),
    _race("marina_bay", "Singapore Grand Prix", year=2026, race_utc=datetime(2026, 10, 11, 12, 0, tzinfo=UTC)),
    _race("austin", "United States Grand Prix", year=2026, race_utc=datetime(2026, 10, 25, 19, 0, tzinfo=UTC)),
    _race("mexico_city", "Mexican Grand Prix", year=2026, race_utc=datetime(2026, 11, 1, 20, 0, tzinfo=UTC)),
    _race("interlagos", "São Paulo Grand Prix", year=2026, race_utc=datetime(2026, 11, 8, 17, 0, tzinfo=UTC)),
    _race("las_vegas", "Las Vegas Grand Prix", year=2026, race_utc=datetime(2026, 11, 21, 6, 0, tzinfo=UTC)),
    _race("lusail", "Qatar Grand Prix", year=2026, race_utc=datetime(2026, 11, 29, 16, 0, tzinfo=UTC)),
    _race("yas_marina", "Abu Dhabi Grand Prix", year=2026, race_utc=datetime(2026, 12, 6, 13, 0, tzinfo=UTC)),
)

_BY_RACE_KEY: dict[str, RaceWeekend] = {w.race_key: w for w in CALENDAR_2026}


def get_race_weekend(race_key: str) -> RaceWeekend | None:
    """Look up a weekend by race_key (e.g. 2026_monaco)."""
    return _BY_RACE_KEY.get(race_key)


def get_next_race_weekend(*, after: datetime | None = None) -> RaceWeekend | None:
    """
    Return the next upcoming race weekend by race_utc.

    Args:
        after: Reference instant (default: now UTC).

    Returns:
        Next RaceWeekend or None if season ended.
    """
    now = after or datetime.now(tz=UTC)
    upcoming = [w for w in CALENDAR_2026 if w.race_utc > now]
    if not upcoming:
        return None
    return min(upcoming, key=lambda w: w.race_utc)


def profile_circuit_key(circuit_key: str) -> str:
    """
    Map calendar circuit_key to a CircuitProfile registry key.

    Madrid is not in the static profile set — use Barcelona as strategist proxy.
    """
    if circuit_key == "madrid":
        return "barcelona"
    return circuit_key
