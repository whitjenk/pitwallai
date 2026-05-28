"""Monaco 2024 historical weekend used for subscriber rehearsal."""

from __future__ import annotations

from datetime import UTC, datetime

from scheduler.calendar import RaceWeekend, _race

MONACO_SESSION_KEY = 9158

MONACO_2024_REHEARSAL: RaceWeekend = _race(
    "monaco",
    "Monaco Grand Prix (2024 sample)",
    year=2024,
    race_utc=datetime(2024, 5, 26, 13, 0, tzinfo=UTC),
)
