"""A small SQLite store keyed by Slack user.

One file remembers each league-mate's team, their locked lineups and cached
OpenF1 responses. Created automatically on first run; no migrations, no Postgres.
"""

from __future__ import annotations

from store.db import (
    cache_get,
    cache_set,
    count_bot_posts,
    forget_user,
    get_league_config,
    get_locked,
    get_team,
    init_db,
    job_has_run,
    list_locked_for_race,
    list_teams,
    lock_lineup,
    mark_job_run,
    record_bot_post,
    set_league_config,
    upsert_team,
)
from store.models import LeagueConfig, LockedLineup, Team

__all__ = [
    "LeagueConfig",
    "LockedLineup",
    "Team",
    "cache_get",
    "cache_set",
    "count_bot_posts",
    "forget_user",
    "get_league_config",
    "get_locked",
    "get_team",
    "init_db",
    "job_has_run",
    "list_locked_for_race",
    "list_teams",
    "lock_lineup",
    "mark_job_run",
    "record_bot_post",
    "set_league_config",
    "upsert_team",
]
