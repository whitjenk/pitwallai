"""Editable price catalog — JSON baseline plus the live refresh overlay.

Prices count as trusted when a successful live refresh (see ``feeds``) landed
within :data:`_TRUSTED_WITHIN_HOURS`, or when the operator pins them with
``PITWALL_PRICES_VERIFIED=1`` after matching in-game values.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

from core.rules import (
    CONSTRUCTOR_PRICES_M,
    DRIVER_PRICES_M,
    MIN_ASSET_PRICE_M,
    _clamp_price,
)

_CATALOG_PATH = Path(__file__).resolve().parent / "prices.json"
# Runtime overlay written by the live F1 Fantasy refresh (gitignored, not the
# committed baseline). Layered on top of prices.json when present.
_LIVE_PATH = Path(__file__).resolve().parent / "prices.live.json"

# A live refresh this recent counts as trusted; past it, replies say so.
_TRUSTED_WITHIN_HOURS = 48

_driver_prices: dict[str, float] = dict(DRIVER_PRICES_M)
_constructor_prices: dict[str, float] = dict(CONSTRUCTOR_PRICES_M)
_updated_at: str | None = None
# When the last successful live refresh landed (set by ``apply_live_prices``).
# Reset by ``load_price_catalog`` so the baseline alone is never "fresh".
_refreshed_at: datetime | None = None
_loaded = False


def load_price_catalog() -> None:
    """Load the baseline prices.json, then overlay the live refresh if present.

    Resets ``_refreshed_at``: reloading the committed baseline is not a live
    refresh, so prices only count as fresh once ``apply_live_prices`` sets a
    real refresh time (on startup the store overlay does this straight after).
    """
    global _driver_prices, _constructor_prices, _updated_at, _refreshed_at, _loaded
    _refreshed_at = None
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
    refreshed_at: datetime | None = None,
) -> None:
    """Overlay live prices onto the in-memory catalog and record the refresh time.

    Args:
        drivers: CODE -> price in M.
        constructors: CODE -> price in M.
        persist: Also write core/prices.live.json (gitignored runtime overlay).
            The Slack app persists through the store instead and passes
            ``persist=False``; only the manual ``scripts/refresh_prices.py`` and
            tests still write the file.
        refreshed_at: When these prices were fetched. Defaults to now. Pass the
            stored value when replaying a cached refresh on startup so the
            freshness window reflects the real fetch, not this process's start.
    """
    global _driver_prices, _constructor_prices, _updated_at, _refreshed_at, _loaded

    if not _loaded:
        load_price_catalog()
    if drivers:
        _driver_prices.update({str(k).upper(): float(v) for k, v in drivers.items()})
    if constructors:
        _constructor_prices.update({str(k).upper(): float(v) for k, v in constructors.items()})
    _refreshed_at = refreshed_at or datetime.now(tz=UTC)
    _updated_at = _refreshed_at.strftime("%Y-%m-%d")
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


def _env_prices_verified() -> bool:
    """True when the operator pinned prices with ``PITWALL_PRICES_VERIFIED``."""
    return os.getenv("PITWALL_PRICES_VERIFIED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def prices_refreshed_at() -> datetime | None:
    """When the last successful live refresh landed, or ``None`` if never."""
    if not _loaded:
        load_price_catalog()
    return _refreshed_at


def prices_fresh(now: datetime | None = None) -> bool:
    """True when a live refresh landed within the trusted window."""
    refreshed = prices_refreshed_at()
    if refreshed is None:
        return False
    now = now or datetime.now(tz=UTC)
    return now - refreshed < timedelta(hours=_TRUSTED_WITHIN_HOURS)


def prices_trusted(now: datetime | None = None) -> bool:
    """True when prices are current enough to reason over.

    Trusted when a live refresh landed within the last
    :data:`_TRUSTED_WITHIN_HOURS`, or when the operator pins them with
    ``PITWALL_PRICES_VERIFIED`` (the override still works for a manual run).
    """
    return _env_prices_verified() or prices_fresh(now)


def _refresh_age_phrase(now: datetime | None = None) -> str | None:
    """Rough age of the last refresh as prose, e.g. "3 days ago"; ``None`` if never."""
    refreshed = prices_refreshed_at()
    if refreshed is None:
        return None
    now = now or datetime.now(tz=UTC)
    seconds = max(0.0, (now - refreshed).total_seconds())
    days = int(seconds // 86400)
    if days >= 1:
        return f"{days} day{'s' if days != 1 else ''} ago"
    hours = int(seconds // 3600)
    if hours >= 1:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return "less than an hour ago"


def prices_staleness_note(now: datetime | None = None) -> str | None:
    """One short line for replies when prices aren't trusted, else ``None``.

    States what's observable — when prices last refreshed — rather than issuing
    an instruction, so personal replies can surface it plainly.
    """
    if prices_trusted(now):
        return None
    phrase = _refresh_age_phrase(now)
    if phrase is None:
        return "_Prices haven't refreshed recently and may be out of date._"
    return f"_Prices last updated {phrase} and may be out of date._"


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
