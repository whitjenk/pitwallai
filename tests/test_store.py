"""Tests for the SQLite store (brief 005).

Every function runs against a fresh ``tmp_path`` DB. No network, no reuse of
the old ``db/`` layer.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import store
from store import db as store_db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the store at an isolated SQLite file for one test."""
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    # Drop the per-path engine so the file handle doesn't leak between tests.
    store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)


def _team(user="U1", team="T1", name="Alice") -> store.Team:
    return store.Team(
        slack_user_id=user,
        slack_team_id=team,
        display_name=name,
        drivers=["VER", "NOR"],
        constructors=["RBR"],
        budget_m=100.5,
        transfers_available=2,
        chips_used={"wildcard": False},
    )


def _lineup(user="U1", race="2026-bahrain", chip=None) -> store.LockedLineup:
    return store.LockedLineup(
        slack_user_id=user,
        race_key=race,
        drivers=["VER", "NOR", "LEC"],
        constructors=["RBR"],
        chip=chip,
        captain="VER",
        model_lineup={"ev": 123.4},
    )


async def test_init_db_is_idempotent(tmp_db):
    await store.init_db()
    await store.init_db()  # second call must not raise
    assert await store.list_teams() == []


async def test_init_db_creates_missing_parent_dir(tmp_path, monkeypatch):
    """PITWALL_DB_PATH into a non-existent directory: the store creates it.

    This is the Railway case — the volume mounts at /data and the DB lives at
    /data/pitwall.sqlite. Pointing at a directory that isn't there yet must
    just work rather than failing to open the file.
    """
    path = tmp_path / "data" / "nested" / "pitwall.sqlite"
    assert not path.parent.exists()
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    try:
        await store.init_db()
        await store.upsert_team(_team())
        assert path.exists()
        assert (await store.get_team("U1")) is not None
    finally:
        store_db._engines.pop(str(path), None)
        store_db._factories.pop(str(path), None)


async def test_upsert_and_get_team(tmp_db):
    await store.init_db()
    await store.upsert_team(_team())
    got = await store.get_team("U1")
    assert got is not None
    assert got.drivers == ["VER", "NOR"]
    assert got.budget_m == 100.5
    assert got.transfers_available == 2
    assert got.chips_used == {"wildcard": False}
    assert got.updated_at is not None


async def test_get_team_missing_returns_none(tmp_db):
    await store.init_db()
    assert await store.get_team("nope") is None


async def test_upsert_team_replaces(tmp_db):
    await store.init_db()
    await store.upsert_team(_team())
    await store.upsert_team(_team(name="Alice II"))
    teams = await store.list_teams()
    assert len(teams) == 1
    assert teams[0].display_name == "Alice II"


async def test_list_teams(tmp_db):
    await store.init_db()
    await store.upsert_team(_team(user="U1"))
    await store.upsert_team(_team(user="U2", name="Bob"))
    users = {t.slack_user_id for t in await store.list_teams()}
    assert users == {"U1", "U2"}


async def test_lock_and_get_locked(tmp_db):
    await store.init_db()
    await store.lock_lineup(_lineup())
    got = await store.get_locked("U1", "2026-bahrain")
    assert got is not None
    assert got.captain == "VER"
    assert got.model_lineup == {"ev": 123.4}
    assert got.locked_at is not None


async def test_get_locked_missing_returns_none(tmp_db):
    await store.init_db()
    assert await store.get_locked("U1", "2026-bahrain") is None


async def test_relock_replaces(tmp_db):
    await store.init_db()
    await store.lock_lineup(_lineup(chip=None))
    await store.lock_lineup(_lineup(chip="wildcard"))
    got = await store.get_locked("U1", "2026-bahrain")
    assert got.chip == "wildcard"
    # Still exactly one row for that user and race.
    assert len(await store.list_locked_for_race("2026-bahrain")) == 1


async def test_list_locked_for_race(tmp_db):
    await store.init_db()
    await store.lock_lineup(_lineup(user="U1"))
    await store.lock_lineup(_lineup(user="U2"))
    await store.lock_lineup(_lineup(user="U1", race="2026-jeddah"))
    locked = await store.list_locked_for_race("2026-bahrain")
    assert {r.slack_user_id for r in locked} == {"U1", "U2"}


async def test_forget_user_leaves_no_rows(tmp_db):
    await store.init_db()
    await store.upsert_team(_team(user="U1"))
    await store.upsert_team(_team(user="U2", name="Bob"))
    await store.lock_lineup(_lineup(user="U1"))
    await store.lock_lineup(_lineup(user="U1", race="2026-jeddah"))

    await store.forget_user("U1")

    assert await store.get_team("U1") is None
    assert await store.get_locked("U1", "2026-bahrain") is None
    assert await store.list_locked_for_race("2026-bahrain") == []
    # The other user is untouched.
    assert await store.get_team("U2") is not None


async def test_cache_set_and_get(tmp_db):
    await store.init_db()
    await store.cache_set("sessions/2026", {"n": 23}, ttl_seconds=3600)
    assert await store.cache_get("sessions/2026") == {"n": 23}


async def test_cache_get_missing_returns_none(tmp_db):
    await store.init_db()
    assert await store.cache_get("missing") is None


async def test_cache_set_replaces(tmp_db):
    await store.init_db()
    await store.cache_set("k", {"v": 1}, ttl_seconds=3600)
    await store.cache_set("k", {"v": 2}, ttl_seconds=3600)
    assert await store.cache_get("k") == {"v": 2}


async def test_expired_cache_returns_none(tmp_db):
    await store.init_db()
    # Write with "now" an hour in the past, so the entry is already older than
    # its 1-second TTL by the time we read it back with the real clock.
    past = datetime.now(UTC) - timedelta(hours=1)
    real_now = store_db._now
    store_db._now = lambda: past
    try:
        await store.cache_set("stale", {"v": 1}, ttl_seconds=1)
    finally:
        store_db._now = real_now
    assert await store.cache_get("stale") is None


def test_store_imports_nothing_forbidden():
    """store/ must not import from db/, whatsapp/, core/, intelligence/."""
    forbidden = {"db", "whatsapp", "core", "intelligence"}
    store_dir = Path(store.__file__).parent
    offenders: list[str] = []
    for path in store_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in forbidden:
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, offenders
