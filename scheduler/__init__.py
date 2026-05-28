"""Race weekend APScheduler — calendar-driven job delivery."""

from scheduler.calendar import CALENDAR_2026, RaceWeekend, get_race_weekend, get_next_race_weekend
from scheduler.jobs import RaceJobContext, register_all_weekend_jobs
from scheduler.runtime import start_race_scheduler, stop_race_scheduler

__all__ = [
    "CALENDAR_2026",
    "RaceWeekend",
    "RaceJobContext",
    "get_race_weekend",
    "get_next_race_weekend",
    "register_all_weekend_jobs",
    "start_race_scheduler",
    "stop_race_scheduler",
]
