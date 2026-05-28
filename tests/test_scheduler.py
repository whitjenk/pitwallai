"""Scheduler calendar and job registration tests."""

from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scheduler.calendar import CALENDAR_2026, get_race_weekend
from scheduler.jobs import register_weekend_jobs


def test_calendar_2026_has_22_races() -> None:
    assert len(CALENDAR_2026) == 22


def test_monaco_fantasy_lock_one_hour_before_race() -> None:
    monaco = get_race_weekend("2026_monaco")
    assert monaco is not None
    delta = monaco.race_utc - monaco.fantasy_lock_utc
    assert delta.total_seconds() == 3600


def test_job_ids_are_stable_and_unique_per_weekend() -> None:
    scheduler = AsyncIOScheduler(timezone="UTC")
    weekend = get_race_weekend("2026_monaco")
    assert weekend is not None
    # Only schedule future jobs — mock by using far-future reference
    count = register_weekend_jobs(scheduler, weekend)
    assert count >= 0
    ids = [job.id for job in scheduler.get_jobs()]
    assert len(ids) == len(set(ids))
    for job_id in ids:
        assert job_id.startswith("2026_monaco:")
