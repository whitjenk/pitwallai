"""Vision-call rate limiting."""

from __future__ import annotations

import pytest

from intelligence.vision_budget import check_vision_budget


@pytest.mark.asyncio
async def test_check_vision_budget_allowed_when_under_cap(monkeypatch):
    async def fake_count(phone, *, hours):
        return 0

    monkeypatch.setattr(
        "intelligence.vision_budget.count_vision_calls",
        fake_count,
    )
    result = await check_vision_budget("+15551234567")
    assert result.allowed


@pytest.mark.asyncio
async def test_check_vision_budget_blocks_phone_hourly(monkeypatch):
    async def fake_count(phone, *, hours):
        if phone is not None and hours == 1:
            return 99
        return 0

    monkeypatch.setattr(
        "intelligence.vision_budget.count_vision_calls",
        fake_count,
    )
    result = await check_vision_budget("+15551234567")
    assert not result.allowed
    assert result.reason == "hourly_phone_cap"
