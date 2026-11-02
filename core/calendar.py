"""
2026 F1 race calendar — all times stored in UTC.

Bahrain and Saudi Arabian Grands Prix are omitted (cancelled for 2026).
Madrid uses circuit_key ``madrid`` (profile fallback to Barcelona in jobs).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.race_key import make_race_key


def _lock_hours_before_quali() -> float:
    """Hours the F1 Fantasy deadline sits before qualifying starts.

    The official game locks transfers at the **start of the first qualifying
    session** (Saturday for a standard weekend), not an hour before. Override
    with ``PITWALL_FANTASY_LOCK_HOURS_BEFORE_QUALI`` if a given weekend differs.
    """
    raw = os.getenv("PITWALL_FANTASY_LOCK_HOURS_BEFORE_QUALI", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 0.0


# OpenF1's free tier refuses all data from 30 minutes before each live session
# until 30 minutes after it ends. Session durations we assume when building the
# pause windows (the game only needs rough ends, not to-the-second timing).
DATA_PAUSE_MARGIN = timedelta(minutes=30)
_PRACTICE_DURATION = timedelta(minutes=60)
_QUALIFYING_DURATION = timedelta(minutes=60)
_RACE_DURATION = timedelta(minutes=120)


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
    is_sprint: bool = False


@dataclass(frozen=True, slots=True)
class Session:
    """One on-track session with its UTC start and end."""

    name: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class Pause:
    """An OpenF1 live-data pause: which session, and when data returns."""

    session: Session
    reopens_at: datetime


def _race(
    circuit_key: str,
    display_name: str,
    *,
    year: int,
    race_utc: datetime,
    fp1_utc: datetime | None = None,
    fp2_utc: datetime | None = None,
    fp3_utc: datetime | None = None,
    qualifying_utc: datetime | None = None,
    is_sprint: bool = False,
) -> RaceWeekend:
    """
    Build a RaceWeekend from race start (UTC).

    Session start times may be given explicitly (the real per-weekend timetable);
    any left as ``None`` fall back to the generic FP1/FP2 Friday, FP3 + Qualifying
    Saturday layout. Fantasy lock is ~1h before qualifying (the real F1 Fantasy
    deadline), not 1h before the race.
    """
    race = race_utc.replace(tzinfo=UTC) if race_utc.tzinfo is None else race_utc
    friday = race.date() - timedelta(days=2)
    saturday = race.date() - timedelta(days=1)
    fp1 = fp1_utc or datetime(friday.year, friday.month, friday.day, 11, 0, tzinfo=UTC)
    fp2 = fp2_utc or datetime(friday.year, friday.month, friday.day, 15, 0, tzinfo=UTC)
    fp3 = fp3_utc or datetime(saturday.year, saturday.month, saturday.day, 11, 0, tzinfo=UTC)
    qualifying = qualifying_utc or datetime(
        saturday.year, saturday.month, saturday.day, 14, 0, tzinfo=UTC
    )
    # NOTE: sprint weekends lock before Friday's sprint qualifying — not modelled
    # here. Verify per-weekend in the live game; override via env if needed.
    fantasy_lock = qualifying - timedelta(hours=_lock_hours_before_quali())
    return RaceWeekend(
        race_key=make_race_key(year, circuit_key),
        circuit_key=circuit_key,
        display_name=display_name,
        fp1_utc=fp1,
        fp2_utc=fp2,
        fp3_utc=fp3,
        qualifying_utc=qualifying,
        race_utc=race,
        fantasy_lock_utc=fantasy_lock,
        is_sprint=is_sprint,
    )


# 2026 confirmed calendar (22 rounds) — race start times approximate UTC
CALENDAR_2026: tuple[RaceWeekend, ...] = (
    _race("melbourne", "Australian Grand Prix", year=2026, race_utc=datetime(2026, 3, 8, 5, 0, tzinfo=UTC)),
    _race("shanghai", "Chinese Grand Prix", year=2026, race_utc=datetime(2026, 3, 15, 7, 0, tzinfo=UTC), is_sprint=True),
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
    _race("austin", "United States Grand Prix", year=2026, race_utc=datetime(2026, 10, 25, 19, 0, tzinfo=UTC), is_sprint=True),
    _race("mexico_city", "Mexican Grand Prix", year=2026, race_utc=datetime(2026, 11, 1, 20, 0, tzinfo=UTC)),
    # The four remaining 2026 rounds carry their real UTC timetables (brief 012);
    # none is a sprint weekend. Earlier rounds keep the generic Fri/Sat layout.
    _race(
        "interlagos", "São Paulo Grand Prix", year=2026,
        fp1_utc=datetime(2026, 11, 6, 15, 30, tzinfo=UTC),
        fp2_utc=datetime(2026, 11, 6, 19, 0, tzinfo=UTC),
        fp3_utc=datetime(2026, 11, 7, 14, 30, tzinfo=UTC),
        qualifying_utc=datetime(2026, 11, 7, 18, 0, tzinfo=UTC),
        race_utc=datetime(2026, 11, 8, 17, 0, tzinfo=UTC),
    ),
    _race(
        "las_vegas", "Las Vegas Grand Prix", year=2026,
        fp1_utc=datetime(2026, 11, 20, 0, 30, tzinfo=UTC),
        fp2_utc=datetime(2026, 11, 20, 4, 0, tzinfo=UTC),
        fp3_utc=datetime(2026, 11, 21, 0, 30, tzinfo=UTC),
        qualifying_utc=datetime(2026, 11, 21, 4, 0, tzinfo=UTC),
        race_utc=datetime(2026, 11, 22, 4, 0, tzinfo=UTC),
    ),
    _race(
        "lusail", "Qatar Grand Prix", year=2026,
        fp1_utc=datetime(2026, 11, 27, 13, 30, tzinfo=UTC),
        fp2_utc=datetime(2026, 11, 27, 17, 0, tzinfo=UTC),
        fp3_utc=datetime(2026, 11, 28, 14, 30, tzinfo=UTC),
        qualifying_utc=datetime(2026, 11, 28, 18, 0, tzinfo=UTC),
        race_utc=datetime(2026, 11, 29, 16, 0, tzinfo=UTC),
    ),
    _race(
        "yas_marina", "Abu Dhabi Grand Prix", year=2026,
        fp1_utc=datetime(2026, 12, 4, 9, 30, tzinfo=UTC),
        fp2_utc=datetime(2026, 12, 4, 13, 0, tzinfo=UTC),
        fp3_utc=datetime(2026, 12, 5, 10, 30, tzinfo=UTC),
        qualifying_utc=datetime(2026, 12, 5, 14, 0, tzinfo=UTC),
        race_utc=datetime(2026, 12, 6, 13, 0, tzinfo=UTC),
    ),
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


# ── OpenF1 live-session lockout windows ───────────────────────────────────────
def sessions(weekend: RaceWeekend) -> list[Session]:
    """The weekend's on-track sessions in order, each with a UTC start and end.

    Durations are the rough fixed lengths the lockout maths needs (practice and
    qualifying 60 min, race 120 min), not official timings.
    """
    return [
        Session("FP1", weekend.fp1_utc, weekend.fp1_utc + _PRACTICE_DURATION),
        Session("FP2", weekend.fp2_utc, weekend.fp2_utc + _PRACTICE_DURATION),
        Session("FP3", weekend.fp3_utc, weekend.fp3_utc + _PRACTICE_DURATION),
        Session("Qualifying", weekend.qualifying_utc, weekend.qualifying_utc + _QUALIFYING_DURATION),
        Session("Race", weekend.race_utc, weekend.race_utc + _RACE_DURATION),
    ]


def data_pause_at(now: datetime) -> Pause | None:
    """The live-data pause covering ``now``, or ``None`` if data is flowing.

    OpenF1's free tier refuses data from ``start − 30 min`` to ``end + 30 min``
    for every session across the season. Returns the first session whose window
    contains ``now``, with the instant the data returns.
    """
    for weekend in CALENDAR_2026:
        for session in sessions(weekend):
            window_start = session.start - DATA_PAUSE_MARGIN
            window_end = session.end + DATA_PAUSE_MARGIN
            if window_start <= now <= window_end:
                return Pause(session=session, reopens_at=window_end)
    return None


def next_unpaused(dt: datetime) -> datetime:
    """``dt`` itself, or — if ``dt`` falls in a pause — that window's end + 10 min.

    Later briefs schedule channel posts with this so they never fire mid-lockout.
    """
    pause = data_pause_at(dt)
    if pause is None:
        return dt
    return pause.reopens_at + timedelta(minutes=10)
