"""STREAK command — season pick accuracy."""

from __future__ import annotations

from sqlalchemy import func, select

from db.models import PickRow
from db.session import get_session
from intelligence.repository import load_season_accuracy_row
from whatsapp.commands._utils import accuracy_bar

_FOOTER = (
    "──────────────────\n"
    "PitWallAI · Not financial advice"
)


async def handle_streak(phone_number: str, race_key: str) -> str:
    _ = phone_number, race_key
    try:
        season = 2026
        row = await load_season_accuracy_row(season)
        async with get_session() as session:
            races_scored = int(
                await session.scalar(
                    select(func.count(func.distinct(PickRow.race_key))).where(
                        PickRow.race_key.like(f"{season}_%"),
                        PickRow.was_correct.is_not(None),
                    )
                )
                or 0
            )

        if row is None or races_scored == 0:
            return (
                "📊 *PitWallAI Hit Rate*\n\n"
                "No races scored yet this season. Check back after Race 1.\n\n"
                f"{_FOOTER}"
            )

        pct = float(row.overall_accuracy)
        bar = accuracy_bar(pct)
        best = row.best_circuit.replace("_", " ").title()
        return (
            f"📊 *PitWallAI Hit Rate · {season}*\n\n"
            f"*{pct:.0f}%* correct picks  {bar}\n"
            f"Races scored: {races_scored}\n"
            f"Best circuit: {best}\n"
            f"Worst circuit: {row.worst_circuit.replace('_', ' ').title()}\n\n"
            f"{_FOOTER}"
        )
    except Exception:
        return "Streak data unavailable right now. Try again after the next race."
