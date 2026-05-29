"""Scheduler context helpers for inbound WhatsApp commands."""

from __future__ import annotations

from datetime import UTC, datetime

from scheduler.calendar import CALENDAR_2026, get_next_race_weekend


def get_current_race_key() -> str:
    """
    Return the race_key for the active or next Grand Prix weekend.

    Uses the next upcoming race on the calendar; if the season has ended,
    returns the most recently completed race.
    """
    now = datetime.now(tz=UTC)
    upcoming = get_next_race_weekend(after=now)
    if upcoming is not None:
        return upcoming.race_key
    completed = [w for w in CALENDAR_2026 if w.race_utc <= now]
    if completed:
        return max(completed, key=lambda w: w.race_utc).race_key
    return CALENDAR_2026[0].race_key
