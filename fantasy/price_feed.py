"""Live F1 Fantasy price feed (official game JSON).

Pulls current driver and constructor prices straight from the official F1
Fantasy game feed so the pick engine reasons over real, current values instead
of a hand-maintained catalog that drifts over the season.

The feed exposes both drivers and constructors keyed by three-letter code
(`DriverTLA`) with a `Value` in millions. Three constructor codes differ from
the codes this app uses and are aliased below.
"""

from __future__ import annotations

import httpx
from loguru import logger

_FEED_URL = "https://fantasy.formula1.com/feeds/drivers/1_en.json"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Feed constructor TLA -> the constructor code used across this codebase.
_CONSTRUCTOR_ALIASES = {"AST": "AM", "AUD": "SAU", "RBS": "RB"}


async def fetch_live_prices(
    *, timeout_s: float = 20.0
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Fetch current prices from the official F1 Fantasy feed.

    Returns:
        (driver_prices, constructor_prices), each mapping CODE -> price in M.

    Raises:
        httpx.HTTPError / KeyError on network or schema failure (caller decides
        whether to degrade to the existing catalog).
    """
    async with httpx.AsyncClient(timeout=timeout_s, headers=_HEADERS) as client:
        resp = await client.get(_FEED_URL)
        resp.raise_for_status()
        rows = resp.json()["Data"]["Value"]

    drivers: dict[str, float] = {}
    constructors: dict[str, float] = {}
    for row in rows:
        tla = str(row.get("DriverTLA") or "").upper()
        value = row.get("Value")
        if not tla or value is None:
            continue
        position = row.get("PositionName")
        if position == "DRIVER":
            drivers[tla] = float(value)
        elif position == "CONSTRUCTOR":
            constructors[_CONSTRUCTOR_ALIASES.get(tla, tla)] = float(value)
    return drivers, constructors


async def refresh_prices_from_live(*, persist: bool = True) -> tuple[int, int]:
    """
    Fetch live prices and apply them to the in-memory catalog (and prices.json).

    Returns:
        (driver_count, constructor_count) applied. (0, 0) on failure.
    """
    from fantasy.price_catalog import apply_live_prices

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
