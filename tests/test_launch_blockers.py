"""Tests for the engineering launch blocker: persistent race-monitor dedup."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


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
