"""One SQLite file, keyed by Slack user, created on first run.

No migrations, no Postgres: ``init_db`` just creates the tables. The DB path
comes from ``PITWALL_DB_PATH`` (default ``./pitwall.sqlite``). The API is async
because Slack Bolt's async app calls it.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from sqlalchemy import JSON, Float, Integer, String, delete, event, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from store.models import LockedLineup, Team

DEFAULT_DB_PATH = "./pitwall.sqlite"

_engines: dict[str, AsyncEngine] = {}
_factories: dict[str, async_sessionmaker] = {}


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    slack_user_id: Mapped[str] = mapped_column(String, primary_key=True)
    slack_team_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    constructors: Mapped[list] = mapped_column(JSON, default=list)
    budget_m: Mapped[float] = mapped_column(Float, default=0.0)
    transfers_available: Mapped[int] = mapped_column(Integer, default=0)
    chips_used: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column()


class LockedLineupRow(Base):
    __tablename__ = "locked_lineups"

    slack_user_id: Mapped[str] = mapped_column(String, primary_key=True)
    race_key: Mapped[str] = mapped_column(String, primary_key=True)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    constructors: Mapped[list] = mapped_column(JSON, default=list)
    chip: Mapped[str | None] = mapped_column(String, nullable=True)
    captain: Mapped[str | None] = mapped_column(String, nullable=True)
    model_lineup: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    locked_at: Mapped[datetime] = mapped_column()


class CacheRow(Base):
    __tablename__ = "openf1_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[object] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column()
    ttl_seconds: Mapped[int] = mapped_column(Integer)


def _db_path() -> str:
    return os.environ.get("PITWALL_DB_PATH", DEFAULT_DB_PATH)


def _engine() -> AsyncEngine:
    """Return the async engine for the current ``PITWALL_DB_PATH``.

    Cached per path so a test's ``tmp_path`` DB gets its own engine without
    disturbing any other.
    """
    path = _db_path()
    engine = _engines.get(path)
    if engine is None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
        _apply_sqlite_pragmas(engine)
        _engines[path] = engine
        _factories[path] = async_sessionmaker(engine, expire_on_commit=False)
    return engine


def _session() -> async_sessionmaker:
    _engine()
    return _factories[_db_path()]


def _apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    """WAL for concurrent reads+writes, busy_timeout to wait on locks.

    Copied from the old ``db/session.py``; keeps local SQLite resilient.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()


def _now() -> datetime:
    return datetime.now(UTC)


async def init_db() -> None:
    """Create the tables if they do not exist. Safe to call on every start."""
    engine = _engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _model(cls, row):  # type: ignore[no-untyped-def]
    return cls.model_validate(row, from_attributes=True) if row else None


async def get_team(slack_user_id: str) -> Team | None:
    async with _session()() as s:
        return _model(Team, await s.get(UserRow, slack_user_id))


async def upsert_team(team: Team) -> None:
    """Insert or replace a user's team."""
    async with _session()() as s:
        row = await s.get(UserRow, team.slack_user_id)
        if row is None:
            row = UserRow(slack_user_id=team.slack_user_id)
            s.add(row)
        row.slack_team_id = team.slack_team_id
        row.display_name = team.display_name
        row.drivers = team.drivers
        row.constructors = team.constructors
        row.budget_m = team.budget_m
        row.transfers_available = team.transfers_available
        row.chips_used = team.chips_used
        row.updated_at = _now()
        await s.commit()


async def list_teams() -> list[Team]:
    async with _session()() as s:
        rows = (await s.execute(select(UserRow))).scalars().all()
        return [_model(Team, r) for r in rows]


async def lock_lineup(lineup: LockedLineup) -> None:
    """Lock a lineup for a race. Re-locking the same race replaces it."""
    async with _session()() as s:
        row = await s.get(LockedLineupRow, (lineup.slack_user_id, lineup.race_key))
        if row is None:
            row = LockedLineupRow(
                slack_user_id=lineup.slack_user_id, race_key=lineup.race_key
            )
            s.add(row)
        row.drivers = lineup.drivers
        row.constructors = lineup.constructors
        row.chip = lineup.chip
        row.captain = lineup.captain
        row.model_lineup = lineup.model_lineup
        row.locked_at = _now()
        await s.commit()


async def get_locked(slack_user_id: str, race_key: str) -> LockedLineup | None:
    async with _session()() as s:
        return _model(LockedLineup, await s.get(LockedLineupRow, (slack_user_id, race_key)))


async def list_locked_for_race(race_key: str) -> list[LockedLineup]:
    async with _session()() as s:
        stmt = select(LockedLineupRow).where(LockedLineupRow.race_key == race_key)
        rows = (await s.execute(stmt)).scalars().all()
        return [_model(LockedLineup, r) for r in rows]


async def forget_user(slack_user_id: str) -> None:
    """Remove the user from every table that stores their data."""
    async with _session()() as s:
        await s.execute(delete(UserRow).where(UserRow.slack_user_id == slack_user_id))
        await s.execute(
            delete(LockedLineupRow).where(
                LockedLineupRow.slack_user_id == slack_user_id
            )
        )
        await s.commit()


async def cache_get(key: str) -> object | None:
    """Return a cached payload, or ``None`` if missing or expired."""
    async with _session()() as s:
        row = await s.get(CacheRow, key)
        if row is None:
            return None
        age = (_now() - _aware(row.fetched_at)).total_seconds()
        if age > row.ttl_seconds:
            return None
        return row.payload


async def cache_set(key: str, payload: object, ttl_seconds: int) -> None:
    async with _session()() as s:
        row = await s.get(CacheRow, key)
        if row is None:
            row = CacheRow(key=key)
            s.add(row)
        row.payload = payload
        row.fetched_at = _now()
        row.ttl_seconds = ttl_seconds
        await s.commit()


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat stored values as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
