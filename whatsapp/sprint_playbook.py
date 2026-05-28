"""Sprint weekend Thursday playbook message."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from intelligence.chip_planner import generate_chip_plan, remaining_races_from_now
from intelligence.repository import get_fantasy_team
from scheduler.calendar import RaceWeekend


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


def _lock_local(weekend: RaceWeekend, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    return weekend.fantasy_lock_utc.astimezone(tz).strftime("%a %H:%M")


async def format_sprint_playbook_message(
    weekend: RaceWeekend,
    timezone: str,
    *,
    phone: str | None = None,
) -> str:
    """Sprint weekend Thursday context (observational)."""
    chip_rating = "MEDIUM"
    chip_types = "Limitless / No Negative"
    reasoning = "Sprint adds extra scoring sessions at this circuit."

    if phone:
        team = await get_fantasy_team(phone)
        if team:
            plan = generate_chip_plan(team, remaining_races_from_now())
            sprint_windows = [w for w in plan.windows if w.is_sprint and w.recommended_chips]
            if sprint_windows:
                best = max(sprint_windows, key=lambda w: w.confidence)
                chip_rating = best.priority
                chips = [c.value for c in best.recommended_chips[:2]]
                chip_types = " / ".join(chips) if chips else chip_types
                reasoning = best.reasoning

    lock = _lock_local(weekend, timezone)
    return _truncate(
        f"🏃 Sprint weekend — {weekend.display_name}\n\n"
        f"⚡ Key differences this weekend:\n"
        f"· FP1 only — no FP2 signal update Friday\n"
        f"· Sprint race scores on Saturday, main race Sunday\n"
        f"· Fantasy lock: {lock}\n\n"
        f"🎴 Chip window: {chip_rating} for {chip_types}\n"
        f"{reasoning}\n\n"
        f"Picks arrive after FP1. Text CHIPS for chip advice.",
        380,
    )
