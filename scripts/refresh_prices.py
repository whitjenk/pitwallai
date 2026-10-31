#!/usr/bin/env python3
"""Refresh F1 Fantasy prices in the store from the official live feed.

Fetches current driver and constructor prices, applies them to the catalog and
caches them in the SQLite store (the same path the Slack app reads on startup).

Usage:
    python scripts/refresh_prices.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import store  # noqa: E402
from core.price_catalog import (  # noqa: E402
    driver_price_m,
    known_driver_codes,
    load_price_catalog,
)
from feeds.fantasy_prices import refresh_prices  # noqa: E402


async def main() -> int:
    load_price_catalog()
    await store.init_db()
    if not await refresh_prices():
        print("Live price refresh failed — prices unchanged.", file=sys.stderr)
        return 1

    top = sorted(known_driver_codes(), key=lambda c: -driver_price_m(c))[:5]
    print("Most expensive drivers now:", ", ".join(f"{c} ${driver_price_m(c):.1f}M" for c in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
