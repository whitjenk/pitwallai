"""A small SQLite store keyed by Slack user.

One file remembers each league-mate's team, their locked lineups and cached
OpenF1 responses. Created automatically on first run; no migrations, no Postgres.
"""

from __future__ import annotations

from store.db import (
    cache_get,
    cache_set,
    forget_user,
    get_locked,
    get_team,
    init_db,
    list_locked_for_race,
    list_teams,
    lock_lineup,
    upsert_team,
)
from store.models import LockedLineup, Team

__all__ = [
    "LockedLineup",
    "Team",
    "cache_get",
    "cache_set",
    "forget_user",
    "get_locked",
    "get_team",
    "init_db",
    "list_locked_for_race",
    "list_teams",
    "lock_lineup",
    "upsert_team",
]
