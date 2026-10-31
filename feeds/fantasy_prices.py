"""Live F1 Fantasy price feed (official game JSON).

Pulls current driver and constructor prices straight from the official F1
Fantasy game feed so the pick engine reasons over real, current values instead
of a hand-maintained catalog that drifts over the season.

The feed exposes both drivers and constructors keyed by three-letter code
(`DriverTLA`) with a `Value` in millions. Three constructor codes differ from
the codes this app uses and are aliased below.

Persistence lives in the store, not a file: Railway's filesystem is wiped on
every deploy, but the SQLite store sits on a mounted volume. On startup the
Slack app replays the cached refresh (:func:`load_prices_from_store`) so prices
are current before the first refresh completes, and survive a redeploy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from loguru import logger

import store
from core.price_catalog import apply_live_prices

_FEED_URL = "https://fantasy.formula1.com/feeds/drivers/1_en.json"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Feed constructor TLA -> the constructor code used across this codebase.
_CONSTRUCTOR_ALIASES = {"AST": "AM", "AUD": "SAU", "RBS": "RB"}

# Store key and TTL for the cached refresh. The 7-day TTL outlives a weekend's
# worth of missed refreshes, so a brief outage still leaves prices to load.
_STORE_KEY = "fantasy_prices"
_STORE_TTL_SECONDS = 7 * 24 * 3600


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


async def refresh_prices(*, now: datetime | None = None) -> bool:
    """Fetch live prices, apply them to the catalog, and cache them in the store.

    Best-effort: a network or schema failure logs a warning and leaves the last
    good prices in place (returns ``False``). Returns ``True`` when a non-empty
    refresh was applied and stored.
    """
    try:
        drivers, constructors = await fetch_live_prices()
    except Exception as exc:  # noqa: BLE001 — refresh is best-effort
        logger.warning("Live price refresh failed, keeping last good prices: {}", exc)
        return False
    if not drivers and not constructors:
        logger.warning("Live price feed returned no prices, keeping last good prices")
        return False

    refreshed_at = now or datetime.now(tz=UTC)
    apply_live_prices(drivers, constructors, persist=False, refreshed_at=refreshed_at)
    await store.cache_set(
        _STORE_KEY,
        {
            "refreshed_at": refreshed_at.isoformat(),
            "source": "fantasy.formula1.com live feed",
            "drivers": drivers,
            "constructors": constructors,
        },
        ttl_seconds=_STORE_TTL_SECONDS,
    )
    logger.info(
        "Live prices applied and cached: {} drivers, {} constructors",
        len(drivers),
        len(constructors),
    )
    return True


async def load_prices_from_store() -> bool:
    """Overlay the last cached refresh onto the catalog, if one is stored.

    Called on startup so prices are current straight away (before the first
    live refresh completes) and survive a redeploy. Returns ``True`` when a
    cached refresh was found and applied.
    """
    payload = await store.cache_get(_STORE_KEY)
    if not isinstance(payload, dict):
        return False

    drivers = {str(k).upper(): float(v) for k, v in (payload.get("drivers") or {}).items()}
    constructors = {
        str(k).upper(): float(v) for k, v in (payload.get("constructors") or {}).items()
    }
    if not drivers and not constructors:
        return False

    refreshed_at = _parse_refreshed_at(payload.get("refreshed_at"))
    apply_live_prices(drivers, constructors, persist=False, refreshed_at=refreshed_at)
    logger.info(
        "Loaded cached prices from store: {} drivers, {} constructors (refreshed {})",
        len(drivers),
        len(constructors),
        refreshed_at.isoformat() if refreshed_at else "unknown",
    )
    return True


def _parse_refreshed_at(raw: object) -> datetime | None:
    """Parse the stored ISO timestamp back to an aware UTC datetime, or ``None``."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
