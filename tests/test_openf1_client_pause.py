"""The store-cached OpenF1 client during a live-session lockout (brief 012).

A fake httpx transport counts outgoing requests, so each test can prove whether
an HTTP call was (or wasn't) made. No real network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import openf1.client as openf1_client_mod
import store
from openf1.cache_keys import cache_key_for
from slack_app import openf1_client
from slack_app.openf1_client import OpenF1Paused, build_client
from store import db as store_db

# São Paulo qualifying 18:00–19:00 UTC → pause window 17:30–19:30.
_DURING_PAUSE = datetime(2026, 11, 7, 18, 30, tzinfo=UTC)
_WINDOW_CLOSE = datetime(2026, 11, 7, 19, 30, tzinfo=UTC)
_NO_PAUSE = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)

_SK = 9991
_LAP_KEY = f"openf1:{cache_key_for('laps', {'session_key': _SK})}"
_STALE_LAPS = [{"session_key": _SK, "driver_number": 44, "lap_number": 7, "lap_duration": 90.5}]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def raise_for_status(self):  # noqa: D401 - httpx.Response shape
        return None

    def json(self):
        return self._data


class _CountingClient:
    """Stand-in for ``httpx.AsyncClient`` that counts GETs instead of calling out."""

    def __init__(self, counter, payload, **_kwargs):
        self._counter = counter
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None):
        self._counter["n"] += 1
        return _Resp(self._payload)


@pytest.fixture
def count_requests(monkeypatch):
    """Patch the client's httpx with a counter; return the counter dict."""
    counter = {"n": 0}

    def factory(**kwargs):
        return _CountingClient(counter, [], **kwargs)

    monkeypatch.setattr(openf1_client_mod.httpx, "AsyncClient", factory)
    return counter


async def _prime_expired_lap_row() -> None:
    """Write a laps row already older than its TTL (fetched two hours ago)."""
    past = datetime.now(UTC) - timedelta(hours=2)
    real_now = store_db._now
    store_db._now = lambda: past
    try:
        await store.cache_set(_LAP_KEY, _STALE_LAPS, ttl_seconds=3600)
    finally:
        store_db._now = real_now


async def test_during_pause_serves_stale_row_without_http(tmp_db, monkeypatch, count_requests):
    await store.init_db()
    await _prime_expired_lap_row()
    monkeypatch.setattr(openf1_client, "_now", lambda: _DURING_PAUSE)

    laps = await build_client().get_laps(_SK)

    assert count_requests["n"] == 0  # stale beats a doomed request
    assert [lap.lap_duration for lap in laps] == [90.5]


async def test_during_pause_miss_raises_without_http(tmp_db, monkeypatch, count_requests):
    await store.init_db()  # empty cache
    monkeypatch.setattr(openf1_client, "_now", lambda: _DURING_PAUSE)

    with pytest.raises(OpenF1Paused) as excinfo:
        await build_client().get_laps(_SK)

    assert count_requests["n"] == 0
    assert excinfo.value.reopens_at == _WINDOW_CLOSE


async def test_outside_pause_expired_row_is_refetched(tmp_db, monkeypatch, count_requests):
    await store.init_db()
    await _prime_expired_lap_row()
    monkeypatch.setattr(openf1_client, "_now", lambda: _NO_PAUSE)

    laps = await build_client().get_laps(_SK)

    assert count_requests["n"] == 1  # expired → one real fetch, as before
    assert laps == []  # the fake transport returns an empty list
