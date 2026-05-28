"""WhatsApp pick message formatting with mandatory char-limit enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from zoneinfo import ZoneInfo

from intelligence.schemas import PickOutput, PickRecommendation
from scheduler.calendar import RaceWeekend

PERSONALIZED_MAX_CHARS = 500
GENERIC_MAX_CHARS = 350
RECAP_MAX_CHARS = 300
PRACTICE_SUMMARY_MAX_CHARS = 300
LIVE_ALERT_MAX_CHARS = 200

_ACCURACY_URL = "pitwallai.app/accuracy"


def _confidence_emoji(confidence: float) -> str:
    if confidence >= 70.0:
        return "🟢"
    if confidence >= 50.0:
        return "🟡"
    return "🔴"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def hours_until_lock(fantasy_lock_utc: datetime, timezone: str) -> int:
    """
    Hours until fantasy lock in the subscriber's local timezone.

    Args:
        fantasy_lock_utc: Lock instant (UTC).
        timezone: IANA timezone string.

    Returns:
        Non-negative whole hours.
    """
    tz = ZoneInfo(timezone)
    now_local = datetime.now(tz=tz)
    lock_local = fantasy_lock_utc.astimezone(tz)
    delta = lock_local - now_local
    return max(0, int(delta.total_seconds() // 3600))


def _short_reason(pick: PickRecommendation, max_len: int = 72) -> str:
    reason = pick.reasoning.split(".")[0].strip()
    if not reason:
        reason = pick.headline
    return _truncate(reason, max_len)


def _opponent_label_from_reason(reasoning: str) -> str | None:
    m = re.search(r"([A-Za-z0-9 _-]{2,40}) likely holds", reasoning)
    if not m:
        return None
    nick = m.group(1).strip()
    if nick.lower() == "opponent":
        return None
    return nick


def format_personalized_picks(
    weekend: RaceWeekend,
    output: PickOutput,
    *,
    timezone: str,
) -> str:
    """
    Format PATH A personalized pick message (max 400 chars).

    Raises:
        AssertionError: If formatted message exceeds char limit.
    """
    picks = output.picks
    if not picks:
        raise ValueError("No picks to format")

    hrs = hours_until_lock(weekend.fantasy_lock_utc, timezone)
    best = picks[0]
    out_d = best.transfer_out or "?"
    in_d = best.transfer_in or best.driver_code
    pts = int(round(best.predicted_points_delta or 0))
    savings = ""
    if "Saves" in best.headline:
        fragment = best.headline.split("Saves", 1)[1].strip()
        savings = fragment.split(".")[0].strip() + " · "
    elif "Costs" in best.headline:
        fragment = best.headline.split("Costs", 1)[1].strip()
        savings = "Costs" + fragment.split(".")[0].strip() + " · "
    money_line = f"💰 {savings}+{pts} pts expected · {int(best.confidence)}% confidence"

    lines = [
        f"🏁 {weekend.display_name} — {hrs} hrs to lock",
        "",
        f"🔄 Best swap: {out_d} → {in_d}",
        money_line,
        f"📻 {_short_reason(best)}",
    ]

    if len(picks) > 1:
        alt = picks[1]
        alt_out = alt.transfer_out or "?"
        alt_in = alt.transfer_in or alt.driver_code
        alt_pts = int(round(alt.predicted_points_delta or 0))
        lines.extend(
            [
                "",
                f"2️⃣ Alt: {alt_out} → {alt_in} (+{alt_pts} pts · {int(alt.confidence)}%)",
            ]
        )

    strategy = (best.league_strategy_applied or "").upper()
    if strategy in {"SAFE", "ATTACK", "BALANCED"}:
        lines.extend(["", f"⚔️ {strategy} play:"])
        if strategy == "ATTACK" and best.is_contrarian:
            lines.append(
                f"🎲 Contrarian: {in_d} — {int(best.confidence)}% conf, "
                f"{(best.ownership_tier or 'UNKNOWN').lower()} ownership. Upside if rivals play safe."
            )
        elif strategy == "SAFE" and (best.ownership_tier or "") == "HIGH":
            lines.append(f"🛡️ Consensus: {in_d} — moves with the league.")
        if best.opponent_conflict:
            opp = _opponent_label_from_reason(best.reasoning)
            if opp:
                lines.append(f"⚠️ {opp} likely holds {in_d} — consider differentiating.")
            else:
                lines.append(f"⚠️ Opponent likely holds {in_d} — consider differentiating.")

    lines.extend(["", f"📊 {_ACCURACY_URL} · Reply HELP for commands"])
    message = "\n".join(lines)
    message = _truncate(message, PERSONALIZED_MAX_CHARS)
    assert len(message) <= PERSONALIZED_MAX_CHARS, (
        f"Personalized message {len(message)} chars exceeds {PERSONALIZED_MAX_CHARS}"
    )
    return message


def format_generic_picks(
    weekend: RaceWeekend,
    output: PickOutput,
    *,
    timezone: str,
) -> str:
    """
    Format PATH B generic pick message (max 350 chars).

    Raises:
        AssertionError: If formatted message exceeds char limit.
    """
    picks = output.picks[:3]
    if not picks:
        raise ValueError("No picks to format")

    hrs = hours_until_lock(weekend.fantasy_lock_utc, timezone)
    lines = [f"🏁 {weekend.display_name} — {hrs} hrs to lock", ""]

    for pick in picks:
        emoji = _confidence_emoji(pick.confidence)
        lines.append(
            f"{emoji} {pick.driver_code} — {int(pick.confidence)}% · {_short_reason(pick, 48)}"
        )

    lines.extend(
        [
            "",
            "📋 Personalise picks → text TEAM",
            f"📊 {_ACCURACY_URL} · Reply HELP",
        ]
    )
    message = "\n".join(lines)
    message = _truncate(message, GENERIC_MAX_CHARS)
    assert len(message) <= GENERIC_MAX_CHARS, (
        f"Generic message {len(message)} chars exceeds {GENERIC_MAX_CHARS}"
    )
    return message


def format_recap_message(
    *,
    circuit_name: str,
    correct_count: int,
    total_picks: int,
    season_accuracy_pct: float,
    swap_note: str | None,
    next_race_name: str | None,
    days_until_next: int | None,
    nudge_team: bool,
) -> str:
    """
    Format post-race recap (max 300 chars).

    Raises:
        AssertionError: If formatted message exceeds char limit.
    """
    lines = [
        f"✅ {circuit_name} results",
        "",
        f"Your picks: {correct_count}/{total_picks} correct",
        f"Season accuracy: {season_accuracy_pct:.0f}%",
    ]
    if swap_note:
        lines.append(swap_note)
    if next_race_name and days_until_next is not None:
        lines.append(f"Next race: {next_race_name} in {days_until_next} days")
    if nudge_team:
        lines.append("Text TEAM for personalised picks")

    message = "\n".join(lines)
    message = _truncate(message, RECAP_MAX_CHARS)
    assert len(message) <= RECAP_MAX_CHARS, (
        f"Recap message {len(message)} chars exceeds {RECAP_MAX_CHARS}"
    )
    return message
