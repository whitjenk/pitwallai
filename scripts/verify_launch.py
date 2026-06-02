#!/usr/bin/env python3
"""Verify production launch configuration before inviting beta users.

Config-only (no network):
    python scripts/verify_launch.py --mode live

Friday dry-run — also hit live OpenF1 to confirm the weekend resolves and the
driver roster matches our static map (run during/after FP1):
    python scripts/verify_launch.py --mode live --live-openf1 --circuit monaco
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_STALE_PRICE_DAYS = 10


async def _check_live_openf1(circuit_key: str, year: int) -> int:
    """Resolve sessions + diff the driver roster against our static map.

    Returns a process exit code (0 ok, 1 hard failure).
    """
    from circuits.profiles import get_circuit_profile
    from intelligence.drivers import _DRIVER_NUMBER_TO_CODE_2026
    from openf1.client import OpenF1Client

    profile = get_circuit_profile(circuit_key)
    if profile is None:
        print(f"  ❌ No circuit profile for '{circuit_key}'")
        return 1
    short_name = profile.openf1_circuit_name
    client = OpenF1Client()

    print(f"\nLive OpenF1 check — {profile.display_name} ({short_name}) {year}")
    failed = False
    session_keys: dict[str, int | None] = {}
    for session_name in ("Practice 1", "Qualifying", "Race"):
        try:
            sk = await client.find_session_key(
                year=year, circuit_short_name=short_name, session_name=session_name
            )
        except Exception as exc:  # network / parse
            print(f"  ❌ {session_name}: lookup error: {exc}")
            failed = True
            continue
        session_keys[session_name] = sk
        if sk is None:
            future = session_name != "Practice 1"
            print(f"  {'⚠️ ' if future else '❌'} {session_name}: "
                  f"{'not published yet' if future else 'MISSING'}")
            if not future:
                failed = True
        else:
            print(f"  ✅ {session_name}: session_key={sk}")

    # Roster diff against whatever session is available (prefer Practice 1).
    probe_sk = next((sk for sk in session_keys.values() if sk is not None), None)
    if probe_sk is not None:
        try:
            roster = await client.get_drivers(probe_sk)
        except Exception as exc:
            print(f"  ⚠️  driver roster fetch failed: {exc}")
            roster = []
        if roster:
            live = {r.driver_number: (r.name_acronym or "").upper() for r in roster}
            mismatches = []
            for num, live_code in sorted(live.items()):
                ours = _DRIVER_NUMBER_TO_CODE_2026.get(num)
                if ours is None:
                    mismatches.append(f"#{num}={live_code} (not in our map)")
                elif live_code and ours != live_code:
                    mismatches.append(f"#{num}: ours={ours} live={live_code}")
            if mismatches:
                print("  ⚠️  driver map mismatches (fix intelligence/drivers.py):")
                for m in mismatches:
                    print(f"       - {m}")
            else:
                print(f"  ✅ driver roster matches static map ({len(live)} drivers)")

    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        default="live",
        choices=["live", "rehearsal"],
        help="Runtime mode to validate (default: live)",
    )
    parser.add_argument(
        "--live-openf1",
        action="store_true",
        help="Also hit live OpenF1 to resolve sessions and diff the driver roster",
    )
    parser.add_argument("--circuit", default="monaco", help="Circuit key for --live-openf1")
    parser.add_argument("--year", type=int, default=2026, help="Season year for --live-openf1")
    args = parser.parse_args()

    from fantasy.price_catalog import (
        catalog_age_days,
        catalog_updated_at,
        load_price_catalog,
        prices_trusted,
    )
    from pitwallai.feature_flags import picks_broadcast_enabled
    from pitwallai.free_models import free_models_only
    from pitwallai.launch_validate import validate_launch_config

    load_price_catalog()
    check = validate_launch_config(mode=args.mode)

    print(f"Mode: {args.mode}")
    print(f"Free models only: {'ON (no billed model calls)' if free_models_only() else 'OFF'}")
    print(f"Picks broadcast: {'ON' if picks_broadcast_enabled() else 'OFF (receipts-only)'}")
    print(f"Prices catalog updated_at: {catalog_updated_at() or 'n/a'}")
    print(f"PITWALL_PRICES_VERIFIED: {prices_trusted()}")

    warnings = list(check.warnings)
    age = catalog_age_days()
    if prices_trusted() and age is not None and age > _STALE_PRICE_DAYS:
        warnings.append(
            f"prices.json is {age} days old — in-game prices change weekly; "
            "re-sync fantasy/prices.json before trusting transfer-swap values"
        )
    if free_models_only():
        import os as _os

        if not _os.getenv("PITWALL_GOOGLE_API_KEY", "").strip():
            warnings.append(
                "free-models-only is ON but PITWALL_GOOGLE_API_KEY is unset — "
                "screenshot (vision) onboarding and the LLM intent fallback are "
                "disabled. Set a free AI Studio key (aistudio.google.com/apikey) "
                "or rely on text TEAM entry + rules-based intent."
            )

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ⚠️  {w}")

    if check.errors:
        print("\nErrors (fix before inviting users):")
        for e in check.errors:
            print(f"  ❌ {e}")
        return 1

    exit_code = 0
    if args.live_openf1:
        exit_code = asyncio.run(_check_live_openf1(args.circuit, args.year))

    if exit_code == 0:
        print("\n✅ Launch configuration OK for", args.mode)
    else:
        print("\n❌ Live OpenF1 preflight failed — do not launch until resolved")
    if args.mode == "live" and picks_broadcast_enabled() and not prices_trusted():
        print(
            "   Note: transfer swaps disabled until you set PITWALL_PRICES_VERIFIED=1 "
            "after updating fantasy/prices.json"
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
