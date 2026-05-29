"""Global monthly spend guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from intelligence.spend_guard import (
    SpendMode,
    _snapshot_from_spent,
    get_spend_guard_cached,
    refresh_spend_guard_cache,
)


def test_degraded_at_cap() -> None:
    snap = _snapshot_from_spent(80.0)
    assert snap.mode == SpendMode.DEGRADED
    assert not snap.llm_allowed
    assert not snap.vision_allowed
    assert not snap.signups_allowed


def test_warn_below_cap() -> None:
    snap = _snapshot_from_spent(60.0)  # 80% of default 75
    assert snap.mode == SpendMode.WARN
    assert snap.llm_allowed


def test_normal_low_spend() -> None:
    snap = _snapshot_from_spent(5.0)
    assert snap.mode == SpendMode.NORMAL


@pytest.mark.asyncio
async def test_refresh_updates_cache(monkeypatch) -> None:
    async def fake_sum(_month: str) -> float:
        return 76.0

    monkeypatch.setattr("intelligence.spend_guard._sum_monthly_spend", fake_sum)
    snap = await refresh_spend_guard_cache()
    assert snap.mode == SpendMode.DEGRADED
    assert not get_spend_guard_cached().llm_allowed


@pytest.mark.asyncio
async def test_record_spend_triggers_refresh(monkeypatch) -> None:
    from contextlib import asynccontextmanager

    from intelligence.spend_guard import record_spend

    mock_refresh = AsyncMock(return_value=_snapshot_from_spent(0.0))
    monkeypatch.setattr("intelligence.spend_guard.refresh_spend_guard_cache", mock_refresh)

    session = AsyncMock()
    session.add = lambda _x: None

    @asynccontextmanager
    async def _fake_session():
        yield session

    monkeypatch.setattr("intelligence.spend_guard.get_session", _fake_session)
    await record_spend("whatsapp", 0.008)
    mock_refresh.assert_awaited_once()
