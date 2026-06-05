#!/usr/bin/env python3
"""Refresh fantasy/prices.json from the official F1 Fantasy live feed.

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

from fantasy.price_catalog import load_price_catalog  # noqa: E402
from fantasy.price_feed import refresh_prices_from_live  # noqa: E402


async def main() -> int:
    load_price_catalog()
    nd, nc = await refresh_prices_from_live(persist=True)
    if not nd and not nc:
        print("Live price refresh failed — prices.json unchanged.", file=sys.stderr)
        return 1
    print(f"Updated fantasy/prices.json: {nd} drivers, {nc} constructors (live F1 Fantasy feed).")

    from fantasy.rules import driver_price_m
    from fantasy.price_catalog import known_driver_codes

    top = sorted(known_driver_codes(), key=lambda c: -driver_price_m(c))[:5]
    print("Most expensive drivers now:", ", ".join(f"{c} ${driver_price_m(c):.1f}M" for c in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
