#!/usr/bin/env python3
"""
Interactive terminal simulator for PitWallAI WhatsApp commands.

Uses the same inbound handler as the production webhook; replies print to
stdout instead of Meta Cloud API.

Usage:
    python scripts/whatsapp_chat.py
    python scripts/whatsapp_chat.py --phone +15555550100

Suggested flow:
    SUBSCRIBE → Europe/London (timezone)
    TEAM      → follow onboarding prompts
    HELP      → command list
    PICKS     → weekend picks (needs network for OpenF1)
    NOR       → driver explanation card
    STREAK    → season hit rate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def _terminal_send(phone: str, message: str) -> None:
    """Stand-in for Meta send_message — prints bot replies."""
    _ = phone
    bar = "─" * 48
    print(f"\n{bar}\n{message}\n{bar}\n", flush=True)


def _patch_outbound() -> None:
    import whatsapp.inbound as inbound_mod
    import whatsapp.sender as sender_mod

    sender_mod.send_message = _terminal_send
    inbound_mod._send_message = _terminal_send


async def _bootstrap() -> None:
    import os

    import intelligence.repository as repo
    from db.session import init_db
    from intelligence.context import init_orchestrator_context

    init_orchestrator_context()
    await init_db()

    if not os.environ.get("DATABASE_URL", "").strip():
        print(
            "Note: DATABASE_URL unset — SUBSCRIBE/TEAM/HISTORY need a DB.\n"
            "      HELP, STREAK (empty), and driver codes still work for smoke tests.\n"
            "      Set DATABASE_URL in .env for full flows.\n"
        )

        async def _no_db_onboarding(_phone: str):
            return None

        repo.get_onboarding_state = _no_db_onboarding
        repo.get_league_onboarding_state = _no_db_onboarding


async def _repl(phone: str) -> None:
    from scheduler.context import get_current_race_key
    from whatsapp.inbound import handle_inbound_text

    race_key = get_current_race_key()
    print(
        f"\nPitWallAI WhatsApp simulator\n"
        f"  Phone:    {phone}\n"
        f"  Weekend:  {race_key}\n"
        f"  Commands: HELP · SUBSCRIBE · TEAM · PICKS · NOR · STREAK · HISTORY\n"
        f"  Also:     LEAGUE · WHY NOR · CHIPS · TRANSFERS · BUDGET · LIVE ON\n"
        f"  Exit:     quit / exit / Ctrl-D\n"
    )

    while True:
        try:
            raw = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw.lower() in {"quit", "exit", "q"}:
            break

        await handle_inbound_text(phone, raw.upper(), raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate PitWallAI WhatsApp commands in the terminal")
    parser.add_argument(
        "--phone",
        default="+15555550100",
        help="Simulated subscriber phone (E.164)",
    )
    args = parser.parse_args()

    asyncio.run(_bootstrap())
    _patch_outbound()
    asyncio.run(_repl(args.phone))


if __name__ == "__main__":
    main()
