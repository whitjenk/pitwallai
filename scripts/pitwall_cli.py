#!/usr/bin/env python3
"""Try every /pitwall command from the terminal, without Slack.

Runs the same handlers the Slack app uses, against a local SQLite file, with live
OpenF1 data and fantasy prices. Each reply is tagged with who would see it in Slack.

Usage:
    python scripts/pitwall_cli.py                      # interactive: type commands, Ctrl-D to quit
    python scripts/pitwall_cli.py team HAM LEC ...     # run one command and exit
    python scripts/pitwall_cli.py --user sam picks     # act as a different league-mate

Data goes to ./pitwall-cli.sqlite by default, so it never touches your real bot's
database. Override with PITWALL_DB_PATH.
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

os.environ.setdefault("PITWALL_DB_PATH", str(PROJECT_ROOT / "pitwall-cli.sqlite"))

import store  # noqa: E402
from core.price_catalog import load_price_catalog  # noqa: E402
from feeds.fantasy_prices import load_prices_from_store, refresh_prices  # noqa: E402
from slack_app.handlers import handle  # noqa: E402
from slack_app.reply import IN_CHANNEL  # noqa: E402

_TEAM_ID = "TCLI"


async def _startup(skip_refresh: bool) -> None:
    await store.init_db()
    load_price_catalog()
    await load_prices_from_store()
    if not skip_refresh:
        try:
            await refresh_prices()
        except Exception as exc:  # same best-effort behaviour as the Slack app
            print(f"(price refresh failed, using last known prices: {exc})")


async def _run(text: str, user: str) -> None:
    result = await handle(text, user_id=f"U-{user}", team_id=_TEAM_ID, display_name=user)
    replies = result if isinstance(result, list) else [result]
    for reply in replies:
        who = "CHANNEL - everyone sees this" if reply.visibility == IN_CHANNEL else f"PRIVATE - only {user} sees this"
        print(f"\n[{who}]\n{reply.text}\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="me", help="league-mate name to act as (default: me)")
    parser.add_argument("--no-refresh", action="store_true", help="skip fetching live prices at startup")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="a /pitwall command, e.g. picks")
    args = parser.parse_args()

    await _startup(args.no_refresh)
    print(f"Database: {os.environ['PITWALL_DB_PATH']}  ·  acting as: {args.user}")

    if args.command:
        await _run(" ".join(args.command), args.user)
        return 0

    print("Type a command as you would after /pitwall (e.g. `help`, `picks`). Ctrl-D to quit.")
    while True:
        try:
            line = input("/pitwall ").strip()
        except EOFError:
            print()
            return 0
        if line:
            await _run(line, args.user)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
