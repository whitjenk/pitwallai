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
║  PitWallAI practice — talk to it like a friend, not a CLI     ║
╠══════════════════════════════════════════════════════════════╣
║  NATURAL LANGUAGE (no exact syntax needed)                   ║
║    should i play a chip?           → chip planner            ║
║    is it worth using my wildcard?  → wildcard detail         ║
║    who should i pick this week?    → picks                   ║
║    how am i doing?                 → your history            ║
║    how accurate are you?           → season hit rate         ║
║    tell me about verstappen        → driver card            ║
║    why is norris so cheap?         → price breakdown         ║
║    turn on race alerts             → LIVE ON                  ║
║    how much budget do i have?      → budget                  ║
║    what can you do?                → help                    ║
║                                                              ║
║  ONBOARDING (needs DATABASE_URL in .env)                     ║
║    1. SUBSCRIBE   2. Europe/London   3. TEAM                 ║
║    4. 12.5  5. NOR,VER,LEC,ALB,HAM  6. MCL,RBR  7. 2         ║
║                                                              ║
║  EXACT COMMANDS still work too                                ║
║    HELP · PICKS · CHIPS · BUDGET · TRANSFERS · STREAK         ║
║    HISTORY · LIVE ON/OFF · WHY NOR · SEASON · NOR (code)      ║
║                                                              ║
║  EDGE CASES (judge the bot)                                  ║
║    hello   → HELP, not a crash                                ║
║    ZZZZ    → unknown → HELP                                   ║
║                                                              ║
║  Simulator shortcuts:  ?  practice  quit                     ║
╚══════════════════════════════════════════════════════════════╝
"""

# Off-by-default feature flags the simulator turns ON so every command is
# explorable locally. A real .env value (loaded first) always wins.
_SIM_FEATURE_FLAGS = {
    "PITWALL_CHIPS_ENABLED": "1",
    "PITWALL_BUDGET_TRANSFERS_ENABLED": "1",
    "PITWALL_SEASON_RECAP_ENABLED": "1",
    "PITWALL_CONSTRUCTOR_STRATEGY_ENABLED": "1",
    "EXPLANATION_CARDS_ENABLED": "true",
    # Never call a billed model in local testing (also the production default).
    "PITWALL_FREE_MODELS_ONLY": "1",
}


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


async def _provision_sqlite_db() -> str:
    """Create an ephemeral SQLite DB with all ORM tables.

    Imports every model registered on ``Base.metadata`` (including
    ``openf1_cache``) before ``create_all``. Returns the temp file path.
    """
    import tempfile

    import openf1.cache  # noqa: F401 — OpenF1CacheEntry on Base.metadata

    from db.models import Base
    from db.session import get_engine

    fd, path = tempfile.mkstemp(prefix="pitwall_sim_", suffix=".sqlite")
    os.close(fd)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{path}"
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return path


async def _seed_sim_practice_data() -> None:
    """Load FP1/FP2 signals into the sim DB when empty (rehearsal seed + OpenF1)."""
    from circuits.profiles import get_circuit_profile
    from intelligence.practice_analyst import analyze_practice_weekend
    from intelligence.repository import load_practice_signals_by_circuit
    from intelligence.rehearsal_cache_seed import seed_rehearsal_practice_signals_if_needed
    from openf1.client import OpenF1Client
    from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
    from pitwallai.agents.radio_intercept.config import PitWallSettings
    from pitwallai.agents.radio_intercept.vector_store import MockVectorStore
    from scheduler.calendar import get_race_weekend, profile_circuit_key
    from scheduler.context import get_current_race_key

    seeded = await seed_rehearsal_practice_signals_if_needed()
    if seeded:
        print(f"  Rehearsal practice seed: {seeded} drivers (monaco demo)")

    race_key = os.environ.get("PITWALL_SIM_RACE_KEY", "").strip() or get_current_race_key()
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return
    profile_key = profile_circuit_key(weekend.circuit_key)
    existing = await load_practice_signals_by_circuit(profile_key)
    if len(existing) >= 5:
        sessions = sorted({s.session for s in existing})
        print(
            f"  Practice signals ready: {len(existing)} drivers on {race_key}"
            f" ({', '.join(sessions)})"
        )
        return

    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        return
    try:
        settings = PitWallSettings.from_env()
        signals = await analyze_practice_weekend(
            client=OpenF1Client(),
            agent=RadioInterceptAgent(settings=settings),
            vector_store=MockVectorStore(embedding_cache_size=32),
            circuit=circuit,
            year=2026,
            persist=True,
        )
        if signals:
            sessions = sorted({s.session for s in signals})
            print(
                f"  OpenF1 FP ingest: {len(signals)} signals for {race_key}"
                f" ({', '.join(sessions)})"
            )
    except Exception as exc:
        print(f"  OpenF1 FP ingest skipped ({exc})")


async def _bootstrap() -> str | None:
    from intelligence.context import init_orchestrator_context

    _load_env_file()
    # Real .env values win (loaded above); otherwise enable everything locally.
    for key, value in _SIM_FEATURE_FLAGS.items():
        os.environ.setdefault(key, value)

    init_orchestrator_context()

    sim_db_path: str | None = None
    if os.environ.get("DATABASE_URL", "").strip():
        # User-provided DB (Postgres) — use the real init path.
        from db.session import init_db

        await init_db()
        await _seed_sim_practice_data()
    else:
        # No DB configured — spin up a throwaway SQLite so every command works.
        sim_db_path = await _provision_sqlite_db()
        from fantasy.price_catalog import load_price_catalog

        load_price_catalog()
        await _seed_sim_practice_data()

    has_explanations = os.environ.get("EXPLANATION_CARDS_ENABLED", "").lower() in {
        "1",
        "true",
        "yes",
    }

    from whatsapp.intent import _llm_enabled_with_key

    nl_llm = _llm_enabled_with_key()

    print("\nEnvironment:")
    print(
        "  Database:                  "
        + ("Postgres (.env)" if sim_db_path is None else f"ephemeral SQLite ({sim_db_path})")
    )
    print(f"  EXPLANATION_CARDS_ENABLED: {'on' if has_explanations else 'off'}")
    print("  Feature flags:             chips, budget/transfers, season ON (simulator)")

    from pitwallai.free_models import free_models_only

    print(
        f"  Free models only:          {'ON — no billed model calls' if free_models_only() else 'OFF'}"
    )
    print(
        f"  Natural-language intent:   rules ON"
        f"{' + free Gemini fallback' if nl_llm else ' (set PITWALL_GOOGLE_API_KEY for free Gemini fallback)'}"
    )
    await _print_practice_summary()
    return sim_db_path


def _apply_sim_race_override() -> str:
    """Pin the simulator to a race_key (e.g. 2026_montreal when FP data exists there)."""
    override = os.environ.get("PITWALL_SIM_RACE_KEY", "").strip()
    if not override:
        return ""
    import scheduler.context as ctx_mod

    ctx_mod.get_current_race_key = lambda: override
    return override


async def _print_practice_summary() -> None:
    """Show FP1/FP2 coverage for calendar weekends."""
    if not os.environ.get("DATABASE_URL", "").strip():
        return
    from datetime import UTC, datetime

    from intelligence.repository import load_practice_signals_by_circuit
    from scheduler.calendar import CALENDAR_2026, get_race_weekend
    from scheduler.context import get_current_race_key

    now = datetime.now(tz=UTC)
    active_key = get_current_race_key()
    print("\nPractice signal coverage (FP1/FP2 in DB):")
    # Active weekend first, then most recent completed races with data.
    keys_to_check: list[str] = [active_key]
    completed = sorted(
        (w for w in CALENDAR_2026 if w.race_utc <= now),
        key=lambda w: w.race_utc,
        reverse=True,
    )
    for w in completed[:3]:
        if w.race_key not in keys_to_check:
            keys_to_check.append(w.race_key)

    best_key: str | None = None
    best_count = 0
    for rk in keys_to_check:
        weekend = get_race_weekend(rk)
        if weekend is None:
            continue
        signals = await load_practice_signals_by_circuit(weekend.circuit_key)
        sessions = sorted({s.session for s in signals})
        marker = " ← active" if rk == active_key else ""
        print(
            f"  {rk}: {len(signals)} drivers"
            + (f" ({', '.join(sessions)})" if sessions else " (none)")
            + marker
        )
        if len(signals) > best_count:
            best_count = len(signals)
            best_key = rk

    if (
        best_key
        and best_key != active_key
        and best_count >= 5
        and not os.environ.get("PITWALL_SIM_RACE_KEY", "").strip()
    ):
        print(
            f"\nTip: FP data is on {best_key} but the calendar active weekend is "
            f"{active_key}. Re-run with:\n"
            f"  PITWALL_SIM_RACE_KEY={best_key} ./scripts/start_simulator.sh"
        )


async def _repl(phone: str, *, show_practice: bool) -> None:
    from scheduler.context import get_current_race_key
    from whatsapp.inbound import handle_inbound_text

    sim_override = _apply_sim_race_override()
    race_key = sim_override or get_current_race_key()
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

    async def _run() -> None:
        # Bootstrap and REPL share one event loop so the async DB engine stays
        # bound to a live loop for the whole session.
        sim_db_path = await _bootstrap()
        _patch_outbound()
        try:
            await _repl(args.phone, show_practice=args.practice)
        finally:
            if sim_db_path and os.path.exists(sim_db_path):
                os.remove(sim_db_path)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
