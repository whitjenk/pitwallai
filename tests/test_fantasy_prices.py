"""Live F1 Fantasy price feed tests (brief 009) — no network, no file overlay.

The official feed is always mocked: :func:`feeds.fantasy_prices.fetch_live_prices`
is monkeypatched so nothing here touches ``fantasy.formula1.com``. Each test runs
against a fresh ``tmp_path`` SQLite store and resets the module-global price
catalog so ordering can't leak a refresh between tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

import store
from core import price_catalog as pc
from core.rules import CONSTRUCTOR_PRICES_M, DRIVER_PRICES_M
from feeds import fantasy_prices
from slack_app import handlers
from store import db as store_db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point the store at an isolated SQLite file for one test."""
    path = tmp_path / "pitwall.sqlite"
    monkeypatch.setenv("PITWALL_DB_PATH", str(path))
    yield path
    engine = store_db._engines.pop(str(path), None)
    store_db._factories.pop(str(path), None)
    if engine is not None:
        engine.sync_engine.dispose()


@pytest.fixture(autouse=True)
def reset_catalog(monkeypatch):
    """Restore the in-memory catalog to the committed baseline around each test."""
    monkeypatch.delenv("PITWALL_PRICES_VERIFIED", raising=False)
    saved = (
        dict(pc._driver_prices),
        dict(pc._constructor_prices),
        pc._updated_at,
        pc._refreshed_at,
        pc._loaded,
    )
    pc._driver_prices = dict(DRIVER_PRICES_M)
    pc._constructor_prices = dict(CONSTRUCTOR_PRICES_M)
    pc._updated_at = None
    pc._refreshed_at = None
    pc._loaded = True  # don't let a getter reload the on-disk overlay mid-test
    yield
    (
        pc._driver_prices,
        pc._constructor_prices,
        pc._updated_at,
        pc._refreshed_at,
        pc._loaded,
    ) = saved


def _mock_fetch(monkeypatch, drivers, constructors):
    async def fake_fetch(*, timeout_s: float = 20.0):
        return dict(drivers), dict(constructors)

    monkeypatch.setattr(fantasy_prices, "fetch_live_prices", fake_fetch)


# ── refresh ───────────────────────────────────────────────────────────────────
async def test_successful_refresh_updates_catalog_and_store(tmp_db, monkeypatch):
    await store.init_db()
    _mock_fetch(monkeypatch, {"VER": 30.0}, {"RBR": 25.0})

    assert await fantasy_prices.refresh_prices() is True

    # Catalog now reflects the fetched prices…
    assert pc.driver_price_m("VER") == pytest.approx(30.0)
    assert pc.constructor_price_m("RBR") == pytest.approx(25.0)
    # …and they're cached in the store, not a file.
    cached = await store.cache_get("fantasy_prices")
    assert isinstance(cached, dict)
    assert cached["drivers"]["VER"] == pytest.approx(30.0)
    assert "refreshed_at" in cached


async def test_failed_refresh_keeps_previous_prices(tmp_db, monkeypatch):
    await store.init_db()
    # Seed a known good price as if a previous refresh had landed.
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False)

    async def boom(*, timeout_s: float = 20.0):
        raise httpx.HTTPError("feed down")

    monkeypatch.setattr(fantasy_prices, "fetch_live_prices", boom)

    assert await fantasy_prices.refresh_prices() is False
    assert pc.driver_price_m("VER") == pytest.approx(30.0)  # unchanged


async def test_empty_feed_is_treated_as_a_failure(tmp_db, monkeypatch):
    await store.init_db()
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False)
    _mock_fetch(monkeypatch, {}, {})

    assert await fantasy_prices.refresh_prices() is False
    assert pc.driver_price_m("VER") == pytest.approx(30.0)
    assert await store.cache_get("fantasy_prices") is None


# ── startup load ────────────────────────────────────────────────────────────
async def test_startup_loads_stored_prices(tmp_db, monkeypatch):
    await store.init_db()
    # A refresh from a prior run cached prices in the store.
    _mock_fetch(monkeypatch, {"VER": 31.5}, {"RBR": 26.0})
    await fantasy_prices.refresh_prices()

    # Simulate a cold catalog (as at process start) before loading from store.
    pc._driver_prices = dict(DRIVER_PRICES_M)
    pc._constructor_prices = dict(CONSTRUCTOR_PRICES_M)
    pc._refreshed_at = None

    assert await fantasy_prices.load_prices_from_store() is True
    assert pc.driver_price_m("VER") == pytest.approx(31.5)
    assert pc.constructor_price_m("RBR") == pytest.approx(26.0)


async def test_load_from_store_is_false_when_nothing_cached(tmp_db):
    await store.init_db()
    assert await fantasy_prices.load_prices_from_store() is False


async def test_prices_survive_a_restart(tmp_db, monkeypatch):
    """Refresh, then a new app instance on the same SQLite file sees them."""
    await store.init_db()
    _mock_fetch(monkeypatch, {"VER": 32.0}, {"RBR": 27.0})
    await fantasy_prices.refresh_prices()

    # "Restart": drop the cached engine/factory for this path and cold the
    # catalog, so the next load must come from the same SQLite file on disk.
    store_db._engines.pop(str(tmp_db), None)
    store_db._factories.pop(str(tmp_db), None)
    pc._driver_prices = dict(DRIVER_PRICES_M)
    pc._constructor_prices = dict(CONSTRUCTOR_PRICES_M)
    pc._refreshed_at = None

    assert await fantasy_prices.load_prices_from_store() is True
    assert pc.driver_price_m("VER") == pytest.approx(32.0)
    assert pc.constructor_price_m("RBR") == pytest.approx(27.0)


# ── freshness / trust ─────────────────────────────────────────────────────────
def test_fresh_refresh_is_trusted_without_the_env_var():
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False)  # refreshed now
    assert pc.prices_trusted() is True
    assert pc.prices_staleness_note() is None


def test_stale_refresh_is_not_trusted():
    three_days_ago = datetime.now(tz=UTC) - timedelta(days=3)
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False, refreshed_at=three_days_ago)
    assert pc.prices_trusted() is False
    note = pc.prices_staleness_note()
    assert note is not None and "3 days ago" in note


def test_env_override_still_trusts_stale_prices(monkeypatch):
    monkeypatch.setenv("PITWALL_PRICES_VERIFIED", "1")
    three_days_ago = datetime.now(tz=UTC) - timedelta(days=3)
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False, refreshed_at=three_days_ago)
    assert pc.prices_trusted() is True
    assert pc.prices_staleness_note() is None


# ── the out-of-date line shows up in picks and team replies ───────────────────
_GOOD_TEAM = "team HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2"


async def _fake_pick_output():
    from core.schemas import PickOutput, PickRecommendation

    return PickOutput(
        picks=[
            PickRecommendation(
                rank=1,
                headline="DRS warm and quick in practice",
                confidence=72.0,
                reasoning="Projected to gain on long-run pace.",
                driver_code="PIA",
                transfer_in="PIA",
                transfer_out="VER",
            )
        ],
        personalized=True,
        circuit_note="High-speed circuit.",
        confidence_note="Two practice sessions available.",
        generated_by="rules",
    )


async def test_team_and_picks_add_out_of_date_line_when_stale(tmp_db, monkeypatch):
    await store.init_db()
    three_days_ago = datetime.now(tz=UTC) - timedelta(days=3)
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False, refreshed_at=three_days_ago)

    async def fake_suggest(team, race_key, client):
        return await _fake_pick_output()

    monkeypatch.setattr(handlers, "suggest_transfers", fake_suggest)

    saved = await handlers.handle(_GOOD_TEAM, user_id="U1", team_id="T1", display_name="Alice")
    assert "may be out of date" in saved.text

    shown = await handlers.handle("team", user_id="U1", team_id="T1", display_name="Alice")
    assert "may be out of date" in shown.text

    picks = await handlers.handle("picks", user_id="U1", team_id="T1", display_name="Alice")
    assert "may be out of date" in picks.text


async def test_team_and_picks_have_no_line_when_fresh(tmp_db, monkeypatch):
    await store.init_db()
    pc.apply_live_prices({"VER": 30.0}, {}, persist=False)  # refreshed now

    async def fake_suggest(team, race_key, client):
        return await _fake_pick_output()

    monkeypatch.setattr(handlers, "suggest_transfers", fake_suggest)

    saved = await handlers.handle(_GOOD_TEAM, user_id="U1", team_id="T1", display_name="Alice")
    assert "out of date" not in saved.text

    picks = await handlers.handle("picks", user_id="U1", team_id="T1", display_name="Alice")
    assert "out of date" not in picks.text
