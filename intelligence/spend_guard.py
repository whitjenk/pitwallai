"""Global monthly spend cap — DB-backed metering with graceful degradation.

When the cap is hit:
  * LLM decoding falls back to rules-only (via decoder_factory)
  * Vision extractors are blocked (via vision_budget)
  * New SUBSCRIBE requests are paused (existing subscribers unaffected)

Per-instance LLM/vision daily caps remain; this is the cross-worker kill-switch.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from loguru import logger
from sqlalchemy import func, select

from db.models import SpendEvent
from db.session import get_session

_CACHE_TTL_S = 30.0
_cache: SpendGuardSnapshot | None = None
_cache_loaded_at: float = 0.0


class SpendMode(str, Enum):
    NORMAL = "normal"
    WARN = "warn"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class SpendGuardSnapshot:
    month_key: str
    monthly_spent_usd: float
    monthly_cap_usd: float
    mode: SpendMode
    llm_allowed: bool
    vision_allowed: bool
    signups_allowed: bool
    pct_of_cap: float


def _month_key(now: datetime | None = None) -> str:
    ts = now or datetime.now(tz=UTC)
    return ts.strftime("%Y-%m")


def _monthly_cap_usd() -> float:
    raw = os.getenv("PITWALL_MONTHLY_SPEND_CAP_USD", "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return 75.0


def _warn_pct() -> float:
    raw = os.getenv("PITWALL_SPEND_WARN_PCT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 80.0


def whatsapp_cost_per_message_usd() -> float:
    raw = os.getenv("PITWALL_WHATSAPP_COST_PER_MESSAGE_USD", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 0.008


def vision_cost_per_call_usd() -> float:
    raw = os.getenv("PITWALL_VISION_COST_PER_CALL_USD", "").strip()
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return 0.001


def _snapshot_from_spent(spent: float) -> SpendGuardSnapshot:
    cap = _monthly_cap_usd()
    pct = (spent / cap * 100.0) if cap > 0 else 100.0
    warn = _warn_pct()
    if pct >= 100.0:
        mode = SpendMode.DEGRADED
    elif pct >= warn:
        mode = SpendMode.WARN
    else:
        mode = SpendMode.NORMAL
    degraded = mode == SpendMode.DEGRADED
    return SpendGuardSnapshot(
        month_key=_month_key(),
        monthly_spent_usd=round(spent, 4),
        monthly_cap_usd=cap,
        mode=mode,
        llm_allowed=not degraded,
        vision_allowed=not degraded,
        signups_allowed=not degraded,
        pct_of_cap=round(pct, 1),
    )


def _fail_open_snapshot() -> SpendGuardSnapshot:
    """No DB — allow operations (local dev)."""
    return SpendGuardSnapshot(
        month_key=_month_key(),
        monthly_spent_usd=0.0,
        monthly_cap_usd=_monthly_cap_usd(),
        mode=SpendMode.NORMAL,
        llm_allowed=True,
        vision_allowed=True,
        signups_allowed=True,
        pct_of_cap=0.0,
    )


async def _sum_monthly_spend(month: str) -> float:
    try:
        async with get_session() as session:
            result = await session.execute(
                select(func.coalesce(func.sum(SpendEvent.amount_usd), 0.0)).where(
                    SpendEvent.month_key == month,
                ),
            )
            return float(result.scalar() or 0.0)
    except ValueError:
        return 0.0


async def refresh_spend_guard_cache() -> SpendGuardSnapshot:
    """Reload monthly spend from Postgres into the process cache."""
    global _cache, _cache_loaded_at
    month = _month_key()
    try:
        spent = await _sum_monthly_spend(month)
    except Exception as exc:
        logger.warning("spend_guard cache refresh failed: {}", exc)
        return get_spend_guard_cached()
    snap = _snapshot_from_spent(spent)
    _cache = snap
    _cache_loaded_at = time.monotonic()
    if snap.mode == SpendMode.WARN:
        logger.warning(
            "Monthly spend at {:.1f}% of cap (${:.2f}/${:.2f})",
            snap.pct_of_cap,
            snap.monthly_spent_usd,
            snap.monthly_cap_usd,
        )
    elif snap.mode == SpendMode.DEGRADED:
        logger.error(
            "Monthly spend cap reached (${:.2f}/${:.2f}) — "
            "degrading to rules-only, blocking vision, pausing signups",
            snap.monthly_spent_usd,
            snap.monthly_cap_usd,
        )
    return snap


def get_spend_guard_cached() -> SpendGuardSnapshot:
    """Sync read for hot paths (LLM decoder). Uses last refreshed cache."""
    if _cache is not None:
        return _cache
    return _fail_open_snapshot()


async def get_spend_guard() -> SpendGuardSnapshot:
    """Fresh spend guard snapshot (refreshes if cache older than TTL)."""
    if _cache is None or time.monotonic() - _cache_loaded_at > _CACHE_TTL_S:
        return await refresh_spend_guard_cache()
    return _cache


async def record_spend(
    category: str,
    amount_usd: float,
    *,
    detail: str | None = None,
) -> SpendGuardSnapshot:
    """Append a spend event and refresh the guard cache."""
    if amount_usd <= 0:
        return await get_spend_guard()
    month = _month_key()
    try:
        async with get_session() as session:
            session.add(
                SpendEvent(
                    month_key=month,
                    category=category[:32],
                    amount_usd=round(amount_usd, 6),
                    detail=(detail or "")[:128] or None,
                ),
            )
    except ValueError:
        return _fail_open_snapshot()
    return await refresh_spend_guard_cache()


def to_public_dict(snap: SpendGuardSnapshot) -> dict[str, object]:
    return {
        "month_key": snap.month_key,
        "monthly_spent_usd": snap.monthly_spent_usd,
        "monthly_cap_usd": snap.monthly_cap_usd,
        "pct_of_cap": snap.pct_of_cap,
        "mode": snap.mode.value,
        "llm_allowed": snap.llm_allowed,
        "vision_allowed": snap.vision_allowed,
        "signups_allowed": snap.signups_allowed,
    }
