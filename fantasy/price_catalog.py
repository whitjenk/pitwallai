"""Editable price catalog — JSON file + optional DB overlay.

Transfer recommendations are gated on ``prices_trusted()`` (operator sets
``PITWALL_PRICES_VERIFIED=1`` after matching in-game values).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from fantasy.rules import (
    CONSTRUCTOR_PRICES_M,
    DRIVER_PRICES_M,
    MIN_ASSET_PRICE_M,
    _clamp_price,
)

_CATALOG_PATH = Path(__file__).resolve().parent / "prices.json"
# Runtime overlay written by the live F1 Fantasy refresh (gitignored, not the
# committed baseline). Layered on top of prices.json when present.
_LIVE_PATH = Path(__file__).resolve().parent / "prices.live.json"

_driver_prices: dict[str, float] = dict(DRIVER_PRICES_M)
_constructor_prices: dict[str, float] = dict(CONSTRUCTOR_PRICES_M)
_updated_at: str | None = None
_loaded = False


def load_price_catalog() -> None:
    """Load the baseline prices.json, then overlay the live refresh if present."""
    global _driver_prices, _constructor_prices, _updated_at, _loaded
    if not _CATALOG_PATH.is_file():
        _loaded = True
        logger.debug("price_catalog: no prices.json — using rules.py defaults")
    else:
        try:
            data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            drivers = data.get("drivers") or {}
            constructors = data.get("constructors") or {}
            if isinstance(drivers, dict) and drivers:
                _driver_prices = {str(k).upper(): float(v) for k, v in drivers.items()}
            if isinstance(constructors, dict) and constructors:
                _constructor_prices = {str(k).upper(): float(v) for k, v in constructors.items()}
            _updated_at = str(data.get("updated_at") or "")
            _loaded = True
            logger.info(
                "price_catalog loaded {} drivers {} constructors (updated_at={})",
                len(_driver_prices),
                len(_constructor_prices),
                _updated_at or "unknown",
            )
        except Exception as exc:
            logger.warning("price_catalog load failed: {} — using rules.py defaults", exc)
            _loaded = True

    # Overlay the live refresh (gitignored) on top of the committed baseline.
    if _LIVE_PATH.is_file():
        try:
            live = json.loads(_LIVE_PATH.read_text(encoding="utf-8"))
            for code, value in (live.get("drivers") or {}).items():
                _driver_prices[str(code).upper()] = float(value)
            for code, value in (live.get("constructors") or {}).items():
                _constructor_prices[str(code).upper()] = float(value)
            if live.get("updated_at"):
                _updated_at = str(live["updated_at"])
            _loaded = True
            logger.info("price_catalog: applied live overlay (updated_at={})", _updated_at)
        except Exception as exc:
            logger.warning("price_catalog: live overlay load failed: {}", exc)


def apply_live_prices(
    drivers: dict[str, float],
    constructors: dict[str, float],
    *,
    persist: bool = True,
) -> None:
    """Overlay live prices onto the in-memory catalog and stamp updated_at=today.

    Args:
        drivers: CODE -> price in M.
        constructors: CODE -> price in M.
        persist: Also write fantasy/prices.live.json (gitignored runtime overlay)
            so the refresh survives restart without touching the committed baseline.
    """
    global _driver_prices, _constructor_prices, _updated_at, _loaded
    from datetime import UTC, datetime

    if not _loaded:
        load_price_catalog()
    if drivers:
        _driver_prices.update({str(k).upper(): float(v) for k, v in drivers.items()})
    if constructors:
        _constructor_prices.update({str(k).upper(): float(v) for k, v in constructors.items()})
    _updated_at = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    _loaded = True
    if persist:
        try:
            _LIVE_PATH.write_text(
                json.dumps(
                    {
                        "updated_at": _updated_at,
                        "source": "fantasy.formula1.com live feed",
                        "drivers": _driver_prices,
                        "constructors": _constructor_prices,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 — persistence is best-effort
            logger.warning("price_catalog: failed to write prices.json: {}", exc)


def prices_trusted() -> bool:
    """True when operator confirmed prices match the official F1 Fantasy app."""
    return os.getenv("PITWALL_PRICES_VERIFIED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def catalog_updated_at() -> str | None:
    if not _loaded:
        load_price_catalog()
    return _updated_at


def catalog_age_days() -> int | None:
    """Days since prices.json ``updated_at``; None if unparseable.

    Used by the launch preflight to warn that in-game prices are stale — they
    change every weekend, so a months-old catalog makes transfer-swap value
    framing wrong even when ``PITWALL_PRICES_VERIFIED=1`` is set."""
    from datetime import UTC, datetime

    raw = (catalog_updated_at() or "").strip()
    if not raw:
        return None
    parsed = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            parsed = None
    if parsed is None:
        return None
    return max(0, (datetime.now(tz=UTC).date() - parsed).days)


def driver_price_m(code: str) -> float:
    if not _loaded:
        load_price_catalog()
    return _clamp_price(_driver_prices.get(code.upper(), 15.0))


def constructor_price_m(code: str) -> float:
    if not _loaded:
        load_price_catalog()
    return _clamp_price(_constructor_prices.get(code.upper(), 10.0))


def known_driver_codes() -> frozenset[str]:
    if not _loaded:
        load_price_catalog()
    return frozenset(_driver_prices.keys())


def known_constructor_codes() -> frozenset[str]:
    if not _loaded:
        load_price_catalog()
    return frozenset(_constructor_prices.keys())


async def overlay_prices_from_db() -> int:
    """Merge latest driver_prices table rows over the JSON catalog."""
    from intelligence.repository import get_all_current_prices

    try:
        db_prices = await get_all_current_prices()
    except ValueError:
        return 0
    if not db_prices:
        return 0
    global _driver_prices
    if not _loaded:
        load_price_catalog()
    _driver_prices.update({k.upper(): float(v) for k, v in db_prices.items()})
    return len(db_prices)
