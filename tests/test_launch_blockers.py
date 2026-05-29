"""Tests for the two engineering launch blockers:
auth on /api/intel/confirm and persistent race-monitor dedup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from intelligence.picks_config import PicksSettings


# ── /api/intel/confirm auth ───────────────────────────────────────────────


@pytest.fixture
def app_client() -> TestClient:
    app = create_app(mode="rehearsal", settings=None)
    app.state.picks_settings = PicksSettings(
        auto_enabled=False,
        interval_seconds=1800,
        race_year=2026,
        circuit_key_override="monaco",
        api_key="test-key",
    )
    app.state.picks_scheduler = MagicMock()
    app.state.picks_scheduler.run_once = AsyncMock(return_value=None)
    return TestClient(app)


def test_confirm_intel_rejects_missing_key(app_client: TestClient) -> None:
    """Unauthenticated callers must not flip verification flags."""
    resp = app_client.post(
        "/api/intel/confirm/00000000-0000-4000-8000-000000000000",
        json={"verified": True},
    )
    assert resp.status_code == 401


def test_confirm_intel_rejects_wrong_key(app_client: TestClient) -> None:
    resp = app_client.post(
        "/api/intel/confirm/00000000-0000-4000-8000-000000000000",
        json={"verified": True},
        headers={"X-PitWall-API-Key": "not-the-key"},
    )
    assert resp.status_code == 401


def test_confirm_intel_with_correct_key_clears_auth(
    app_client: TestClient,
) -> None:
    """A valid key clears the auth dependency. The endpoint then 404s
    because the test session has no transmission with that id — the
    important thing is the status code is not 401."""
    resp = app_client.post(
        "/api/intel/confirm/00000000-0000-4000-8000-000000000000",
        json={"verified": True},
        headers={"X-PitWall-API-Key": "test-key"},
    )
    assert resp.status_code in (400, 404)


def test_confirm_intel_503_when_server_key_unconfigured(
    app_client: TestClient,
) -> None:
    """Mirrors the picks endpoint contract: 503 when server has no key set."""
    app_client.app.state.picks_settings = PicksSettings(
        auto_enabled=False,
        interval_seconds=1800,
        race_year=2026,
        circuit_key_override="monaco",
        api_key="",
    )
    resp = app_client.post(
        "/api/intel/confirm/00000000-0000-4000-8000-000000000000",
        json={"verified": True},
        headers={"X-PitWall-API-Key": "anything"},
    )
    assert resp.status_code == 503


# ── Race monitor dedup hydration ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_dedup_rehydrate_populates_in_memory_sets() -> None:
    """Previously-persisted dedup keys must populate the in-memory sets
    so a Railway restart doesn't re-broadcast events."""
    import agents.race_monitor as rm

    race_key = "2026_rehydrate_test"
    persisted_msgs = {"msg-A", "msg-B"}
    persisted_pits = {"55:23", "55:38"}

    rm._seen_messages.pop(race_key, None)
    rm._seen_pit_stops.pop(race_key, None)

    with patch(
        "agents.race_monitor.load_seen_keys",
        new=AsyncMock(side_effect=[persisted_msgs, persisted_pits]),
    ):
        await rm._rehydrate_dedup(race_key)

    assert rm._seen_messages[race_key] == persisted_msgs
    assert rm._seen_pit_stops[race_key] == persisted_pits

    rm._seen_messages.pop(race_key, None)
    rm._seen_pit_stops.pop(race_key, None)


@pytest.mark.asyncio
async def test_dedup_rehydrate_failure_does_not_raise() -> None:
    """A transient DB hiccup at rehydration time must not crash the monitor."""
    import agents.race_monitor as rm

    race_key = "2026_rehydrate_failure"
    rm._seen_messages.pop(race_key, None)
    rm._seen_pit_stops.pop(race_key, None)

    with patch(
        "agents.race_monitor.load_seen_keys",
        new=AsyncMock(side_effect=RuntimeError("db hiccup")),
    ):
        # Must not raise.
        await rm._rehydrate_dedup(race_key)

    # In-memory sets remain empty.
    assert race_key not in rm._seen_messages or rm._seen_messages[race_key] == set()
    assert race_key not in rm._seen_pit_stops or rm._seen_pit_stops[race_key] == set()


@pytest.mark.asyncio
async def test_dedup_rehydrate_merges_with_existing_keys() -> None:
    """If the monitor already has in-memory keys (resumed task), DB load
    must merge rather than overwrite — neither side is authoritative."""
    import agents.race_monitor as rm

    race_key = "2026_rehydrate_merge"
    rm._seen_messages.pop(race_key, None)
    rm._seen_pit_stops.pop(race_key, None)

    rm._seen_messages[race_key].add("in-mem-only")
    rm._seen_pit_stops[race_key].add("99:1")

    with patch(
        "agents.race_monitor.load_seen_keys",
        new=AsyncMock(side_effect=[{"persisted-only"}, {"55:23"}]),
    ):
        await rm._rehydrate_dedup(race_key)

    assert rm._seen_messages[race_key] == {"in-mem-only", "persisted-only"}
    assert rm._seen_pit_stops[race_key] == {"99:1", "55:23"}

    rm._seen_messages.pop(race_key, None)
    rm._seen_pit_stops.pop(race_key, None)
