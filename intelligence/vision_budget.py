"""Per-phone hourly + global daily caps on Gemini Vision calls."""

from __future__ import annotations

import os
from dataclasses import dataclass

from intelligence.repository import count_vision_calls, record_vision_call

_DEFAULT_PHONE_HOURLY = 5
_DEFAULT_GLOBAL_DAILY = 5000


def _phone_hourly_limit() -> int:
    raw = os.getenv("PITWALL_VISION_MAX_PER_PHONE_HOUR", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_PHONE_HOURLY


def _global_daily_limit() -> int:
    raw = os.getenv("PITWALL_VISION_MAX_GLOBAL_DAY", "").strip()
    if raw.isdigit():
        return max(1, int(raw))
    return _DEFAULT_GLOBAL_DAILY


@dataclass(frozen=True)
class VisionBudgetResult:
    allowed: bool
    reason: str = ""


async def check_vision_budget(phone: str) -> VisionBudgetResult:
    """Return whether another vision call is permitted for this phone."""
    phone_count = await count_vision_calls(phone, hours=1)
    if phone_count >= _phone_hourly_limit():
        return VisionBudgetResult(
            allowed=False,
            reason="hourly_phone_cap",
        )
    global_count = await count_vision_calls(None, hours=24)
    if global_count >= _global_daily_limit():
        return VisionBudgetResult(
            allowed=False,
            reason="global_daily_cap",
        )
    return VisionBudgetResult(allowed=True)


async def record_vision_call_for(phone: str, kind: str) -> None:
    await record_vision_call(phone, kind)
