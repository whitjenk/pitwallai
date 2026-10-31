"""Shim — the live price feed moved to :mod:`feeds.fantasy_prices` (brief 009).

Kept so the retired ``scripts/`` entry points that still import this path keep
working. New code should import from ``feeds.fantasy_prices``.
"""

from __future__ import annotations

from feeds.fantasy_prices import fetch_live_prices

__all__ = ["fetch_live_prices", "refresh_prices_from_live"]


async def refresh_prices_from_live(*, persist: bool = True) -> tuple[int, int]:
    """Fetch live prices and apply them to the in-memory catalog (file persist).

    Legacy helper for the hand-run ``scripts/refresh_prices.py``. The Slack app
    does not use this — it refreshes through ``feeds.fantasy_prices`` and the
    store. Returns ``(driver_count, constructor_count)`` applied, ``(0, 0)`` on
    failure.
    """
    from loguru import logger

    from core.price_catalog import apply_live_prices

    try:
        drivers, constructors = await fetch_live_prices()
    except Exception as exc:  # noqa: BLE001 — refresh is best-effort
        logger.warning("Live price refresh failed: {}", exc)
        return (0, 0)
    if not drivers and not constructors:
        return (0, 0)
    apply_live_prices(drivers, constructors, persist=persist)
    logger.info(
        "Live prices applied: {} drivers, {} constructors",
        len(drivers),
        len(constructors),
    )
    return (len(drivers), len(constructors))
