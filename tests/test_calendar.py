"""Calendar timetables and OpenF1 lockout windows (brief 012).

No network, no store — ``core.calendar`` is pure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core import calendar as cal

# The real 2026 UTC timetable for the four remaining rounds (brief 012 table).
# {race_key: {session: (Y, M, D, h, m)}}
_EXPECTED = {
    "2026_interlagos": {
        "fp1_utc": (2026, 11, 6, 15, 30),
        "fp2_utc": (2026, 11, 6, 19, 0),
        "fp3_utc": (2026, 11, 7, 14, 30),
        "qualifying_utc": (2026, 11, 7, 18, 0),
        "race_utc": (2026, 11, 8, 17, 0),
    },
    "2026_las_vegas": {
        "fp1_utc": (2026, 11, 20, 0, 30),
        "fp2_utc": (2026, 11, 20, 4, 0),
        "fp3_utc": (2026, 11, 21, 0, 30),
        "qualifying_utc": (2026, 11, 21, 4, 0),
        "race_utc": (2026, 11, 22, 4, 0),
    },
    "2026_lusail": {
        "fp1_utc": (2026, 11, 27, 13, 30),
        "fp2_utc": (2026, 11, 27, 17, 0),
        "fp3_utc": (2026, 11, 28, 14, 30),
        "qualifying_utc": (2026, 11, 28, 18, 0),
        "race_utc": (2026, 11, 29, 16, 0),
    },
    "2026_yas_marina": {
        "fp1_utc": (2026, 12, 4, 9, 30),
        "fp2_utc": (2026, 12, 4, 13, 0),
        "fp3_utc": (2026, 12, 5, 10, 30),
        "qualifying_utc": (2026, 12, 5, 14, 0),
        "race_utc": (2026, 12, 6, 13, 0),
    },
}


def _wk(race_key: str) -> cal.RaceWeekend:
    w = cal.get_race_weekend(race_key)
    assert w is not None
    return w


def test_remaining_races_match_the_published_timetable() -> None:
    """All 20 session times (4 races × 5 sessions) match the brief's table."""
    for race_key, sessions in _EXPECTED.items():
        w = _wk(race_key)
        for field, (y, mo, d, h, mi) in sessions.items():
            assert getattr(w, field) == datetime(y, mo, d, h, mi, tzinfo=UTC), (
                f"{race_key}.{field}"
            )


def test_remaining_races_are_not_sprints() -> None:
    for race_key in _EXPECTED:
        assert _wk(race_key).is_sprint is False


def test_fantasy_lock_is_qualifying_start() -> None:
    # Default lock offset is 0h (lock at qualifying start).
    w = _wk("2026_interlagos")
    assert w.fantasy_lock_utc == w.qualifying_utc


def test_earlier_races_keep_the_generic_timetable() -> None:
    # Monaco (round 6) was not retimed: generic FP1 11:00 / quali 14:00 UTC.
    w = _wk("2026_monaco")
    assert w.fp1_utc.hour == 11 and w.fp1_utc.minute == 0
    assert w.fp2_utc.hour == 15 and w.fp2_utc.minute == 0
    assert w.fp3_utc.hour == 11 and w.fp3_utc.minute == 0
    assert w.qualifying_utc.hour == 14 and w.qualifying_utc.minute == 0


# ── sessions() ────────────────────────────────────────────────────────────────
def test_sessions_names_and_durations() -> None:
    w = _wk("2026_interlagos")
    sessions = cal.sessions(w)
    assert [s.name for s in sessions] == ["FP1", "FP2", "FP3", "Qualifying", "Race"]
    fp1, fp2, fp3, quali, race = sessions
    assert fp1.end - fp1.start == timedelta(minutes=60)
    assert quali.end - quali.start == timedelta(minutes=60)
    assert race.end - race.start == timedelta(minutes=120)
    assert quali.start == w.qualifying_utc


# ── data_pause_at() ───────────────────────────────────────────────────────────
# São Paulo qualifying: 18:00–19:00 UTC → pause window 17:30–19:30.
_QUALI_START = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)
_WINDOW_OPEN = datetime(2026, 11, 7, 17, 30, tzinfo=UTC)  # start − 30 min
_WINDOW_CLOSE = datetime(2026, 11, 7, 19, 30, tzinfo=UTC)  # end + 30 min


def test_pause_at_window_start_edge() -> None:
    pause = cal.data_pause_at(_WINDOW_OPEN)
    assert pause is not None
    assert pause.session.name == "Qualifying"
    assert pause.reopens_at == _WINDOW_CLOSE


def test_pause_mid_session() -> None:
    pause = cal.data_pause_at(_QUALI_START + timedelta(minutes=20))
    assert pause is not None and pause.session.name == "Qualifying"


def test_pause_at_window_end_edge() -> None:
    assert cal.data_pause_at(_WINDOW_CLOSE) is not None


def test_no_pause_just_outside_window() -> None:
    assert cal.data_pause_at(_WINDOW_OPEN - timedelta(minutes=1)) is None
    assert cal.data_pause_at(_WINDOW_CLOSE + timedelta(minutes=1)) is None


# ── next_unpaused() ───────────────────────────────────────────────────────────
def test_next_unpaused_moves_a_time_inside_a_window() -> None:
    moved = cal.next_unpaused(_QUALI_START)
    assert moved == _WINDOW_CLOSE + timedelta(minutes=10)


def test_next_unpaused_leaves_free_times_alone() -> None:
    free = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
    assert cal.next_unpaused(free) == free
