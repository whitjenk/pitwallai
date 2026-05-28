"""Post-race counterfactual WhatsApp messages."""

from __future__ import annotations

from intelligence.counterfactual import CounterfactualRecap
from scheduler.calendar import get_next_race_weekend
from datetime import UTC, datetime


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_counterfactual_whatsapp(
    recap: CounterfactualRecap,
    *,
    next_race_name: str | None = None,
    days_until_next: int | None = None,
) -> str:
    """
    Neutral post-race recap (max 320 chars excluding share line).

    Never mocks missed picks; no apology language.
    """
    circuit = recap.circuit_label or recap.race_key.replace("_", " ").title()
    share_url = f"pitwallai.app/recap/{recap.share_token}"

    if recap.picks_correct >= 2:
        lines = [
            f"✅ {circuit} recap",
            "",
            f"{recap.picks_correct}/{recap.picks_total} picks scored 🎯",
        ]
        if recap.best_pick_driver and recap.best_pick_driver != "n/a":
            sign = "+" if recap.best_pick_delta >= 0 else ""
            lines.append(f"Best: {recap.best_pick_driver} {sign}{recap.best_pick_delta:.0f}pts")
        if recap.league_position_delta is not None and recap.league_position_delta > 0:
            lines.append(f"Moved up {recap.league_position_delta} in your league")
        if recap.vs_no_change_delta > 0:
            lines.append(
                f"Recommended swap gained +{recap.vs_no_change_delta:.0f}pts "
                "vs keeping your original team."
            )
        lines.append(f"Full recap: {share_url}")
    else:
        lines = [
            f"📊 {circuit} recap",
            "",
            f"{recap.picks_correct}/{recap.picks_total} this weekend.",
        ]
        if recap.best_pick_driver and recap.best_pick_driver != "n/a" and recap.best_pick_delta != 0:
            sign = "+" if recap.best_pick_delta >= 0 else ""
            lines.append(f"Best: {recap.best_pick_driver} {sign}{recap.best_pick_delta:.0f}pts.")
        else:
            lines.append("Tough circuit for predictions.")
        lines.append(f"Season GP hit rate: {recap.season_accuracy_pct:.0f}%")
        if next_race_name and days_until_next is not None:
            lines.append(f"Next race: {next_race_name} in {days_until_next} days")
        lines.append(share_url)

    return _truncate("\n".join(lines), 320)


def format_share_card_line(share_token: str) -> str:
    """Append to counterfactual (under 50 chars)."""
    return _truncate(f"📸 Share: pitwallai.app/recap/{share_token}", 50)


def resolve_next_race() -> tuple[str | None, int | None]:
    nxt = get_next_race_weekend(after=datetime.now(tz=UTC))
    if nxt is None:
        return None, None
    days = max(0, (nxt.race_utc - datetime.now(tz=UTC)).days)
    return nxt.display_name, days
