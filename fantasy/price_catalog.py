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

_driver_prices: dict[str, float] = dict(DRIVER_PRICES_M)
_constructor_prices: dict[str, float] = dict(CONSTRUCTOR_PRICES_M)
_updated_at: str | None = None
_loaded = False


def load_price_catalog() -> None:
    """Load fantasy/prices.json if present; fall back to rules.py defaults."""
    global _driver_prices, _constructor_prices, _updated_at, _loaded
    if not _CATALOG_PATH.is_file():
        _loaded = True
        logger.debug("price_catalog: no prices.json — using rules.py defaults")
        return
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
