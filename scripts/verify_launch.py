#!/usr/bin/env python3
"""Verify production launch configuration before inviting beta users.

Usage:
    cp .env.example .env   # fill in values
    python scripts/verify_launch.py
    python scripts/verify_launch.py --mode live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        default="live",
        choices=["live", "rehearsal"],
        help="Runtime mode to validate (default: live)",
    )
    args = parser.parse_args()

    from fantasy.price_catalog import catalog_updated_at, load_price_catalog, prices_trusted
    from pitwallai.launch_validate import validate_launch_config

    load_price_catalog()
    check = validate_launch_config(mode=args.mode)

    print(f"Mode: {args.mode}")
    print(f"Prices catalog updated_at: {catalog_updated_at() or 'n/a'}")
    print(f"PITWALL_PRICES_VERIFIED: {prices_trusted()}")

    if check.warnings:
        print("\nWarnings:")
        for w in check.warnings:
            print(f"  ⚠️  {w}")

    if check.errors:
        print("\nErrors (fix before inviting users):")
        for e in check.errors:
            print(f"  ❌ {e}")
        return 1

    print("\n✅ Launch configuration OK for", args.mode)
    if args.mode == "live" and not prices_trusted():
        print(
            "   Note: transfer swaps disabled until you set PITWALL_PRICES_VERIFIED=1 "
            "after updating fantasy/prices.json"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
