#!/usr/bin/env python3
"""
Interactive terminal simulator for PitWallAI WhatsApp commands.

Uses the same inbound handler as the production webhook; replies print to
stdout instead of Meta Cloud API.

Usage:
    python scripts/whatsapp_chat.py
    python scripts/whatsapp_chat.py --practice    # guided question checklist
    python scripts/whatsapp_chat.py --phone +15555550100
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PRACTICE_CHECKLIST = """
╔══════════════════════════════════════════════════════════════╗
║  PitWallAI practice — type these at the You> prompt          ║
╠══════════════════════════════════════════════════════════════╣
║  ONBOARDING (needs DATABASE_URL in .env)                     ║
║    1. SUBSCRIBE                                              ║
║    2. Europe/London          ← your timezone (IANA)          ║
║    3. TEAM                   ← start team setup              ║
║    4. 12.5                 ← budget left ($M) example       ║
║    5. NOR,VER,LEC,ALB,HAM    ← five drivers                 ║
║    6. MCL,RBR                ← two constructors             ║
║    7. 2                      ← transfers banked             ║
║                                                              ║
║  CORE COMMANDS (what users text on race weekend)             ║
║    HELP          — full command list                         ║
║    PICKS         — this weekend's recommendations            ║
║    NOR           — driver brief (try VER, LEC, BOT too)      ║
║    STREAK        — public season hit rate                    ║
║    HISTORY       — your last 3 scored races                  ║
║                                                              ║
║  DEEPER QUESTIONS (same as texting WHY / extras)             ║
║    WHY NOR       — price prediction breakdown                ║
║    WHY CONSTRUCTOR FER                                       ║
║    CHIPS         — chip planner summary                      ║
║    TRANSFERS     — transfers banked                          ║
║    BUDGET        — team value snapshot                       ║
║    LIVE ON       — enable Sunday race alerts                 ║
║                                                              ║
║  EDGE CASES (judge the bot)                                  ║
║    hello         — should show HELP, not crash               ║
║    ZZZZ          — unknown code → HELP                        ║
║    PICKS         — before team setup vs after                ║
║                                                              ║
║  Simulator shortcuts:  ?  practice  quit                     ║
╚══════════════════════════════════════════════════════════════╝
"""


def _load_env_file() -> None:
    """Load .env into os.environ when present (does not override existing)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


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
    import intelligence.repository as repo
    from db.session import init_db
    from intelligence.context import init_orchestrator_context

    _load_env_file()
    init_orchestrator_context()
    await init_db()

    has_db = bool(os.environ.get("DATABASE_URL", "").strip())
    has_explanations = os.environ.get("EXPLANATION_CARDS_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }

    print("\nEnvironment:")
    print(f"  DATABASE_URL:              {'set' if has_db else 'missing (limited flows)'}")
    print(f"  EXPLANATION_CARDS_ENABLED: {'on' if has_explanations else 'off'}")

    if not has_db:
        print(
            "\nTip: copy .env.example → .env and set DATABASE_URL for SUBSCRIBE/TEAM/HISTORY.\n"
        )

        async def _no_db_onboarding(_phone: str):
            return None

        repo.get_onboarding_state = _no_db_onboarding
        repo.get_league_onboarding_state = _no_db_onboarding


async def _repl(phone: str, *, show_practice: bool) -> None:
    from scheduler.context import get_current_race_key
    from whatsapp.inbound import handle_inbound_text

    race_key = get_current_race_key()
    if show_practice:
        print(PRACTICE_CHECKLIST)

    print(
        f"\nPitWallAI WhatsApp simulator\n"
        f"  Phone:    {phone}\n"
        f"  Weekend:  {race_key}\n"
        f"  Type messages exactly as you would on WhatsApp.\n"
        f"  Shortcuts: ? or practice (checklist) · quit\n"
    )

    while True:
        try:
            raw = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        lowered = raw.lower()
        if lowered in {"quit", "exit", "q"}:
            break
        if lowered in {"?", "practice", "help me", "scenarios"}:
            print(PRACTICE_CHECKLIST)
            continue

        await handle_inbound_text(phone, raw.upper(), raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate PitWallAI WhatsApp commands in the terminal")
    parser.add_argument(
        "--phone",
        default="+15555550100",
        help="Simulated subscriber phone (E.164)",
    )
    parser.add_argument(
        "--practice",
        action="store_true",
        help="Show guided practice checklist at startup",
    )
    args = parser.parse_args()

    asyncio.run(_bootstrap())
    _patch_outbound()
    asyncio.run(_repl(args.phone, show_practice=args.practice))


if __name__ == "__main__":
    main()
