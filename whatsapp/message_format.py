"""WhatsApp pick message formatting with mandatory char-limit enforcement."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from zoneinfo import ZoneInfo

from intelligence.schemas import PickOutput, PickRecommendation
from scheduler.calendar import RaceWeekend

# Core body limits (footer appended after — see broadcast footer constants).
PERSONALIZED_MAX_CHARS_CORE = 400
GENERIC_MAX_CHARS_CORE = 350
PICK_FOOTER_MAX_CHARS = 52  # Exact footer string length (never truncated)
PERSONALIZED_MAX_CHARS_TOTAL = PERSONALIZED_MAX_CHARS_CORE + PICK_FOOTER_MAX_CHARS
GENERIC_MAX_CHARS_TOTAL = GENERIC_MAX_CHARS_CORE + PICK_FOOTER_MAX_CHARS

# Back-compat aliases used by tests during migration.
PERSONALIZED_MAX_CHARS = PERSONALIZED_MAX_CHARS_TOTAL
GENERIC_MAX_CHARS = GENERIC_MAX_CHARS_TOTAL

RECAP_MAX_CHARS = 300
SEASON_RECAP_MAX_CHARS = 700
PRACTICE_SUMMARY_MAX_CHARS = 300
LIVE_ALERT_MAX_CHARS = 200

PICK_BROADCAST_FOOTER = "ℹ️ Fan tool · Not affiliated with F1 Fantasy or ESPN"

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


def append_pick_broadcast_footer(core: str) -> str:
    """Append mandatory legal footer after core pick body (never truncated)."""
    core = core.rstrip()
    return f"{core}\n\n{PICK_BROADCAST_FOOTER}"


def _finalize_pick_broadcast(core: str, *, core_limit: int, total_limit: int) -> str:
    """Truncate core only, then append footer; footer is never dropped."""
    core = _truncate(core, core_limit)
    message = append_pick_broadcast_footer(core)
    assert PICK_BROADCAST_FOOTER in message
    assert len(message) <= total_limit, (
        f"Pick broadcast {len(message)} chars exceeds {total_limit} (core limit {core_limit})"
    )
    return message


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


def _shrink_core_for_limit(lines: list[str], best: PickRecommendation, core_limit: int) -> str:
    """Prefer shortening the reasoning line before dropping the legal footer."""
    reason_cap = 72
    while reason_cap >= 24:
        rebuilt = list(lines)
        for idx, line in enumerate(rebuilt):
            if line.startswith("📻 "):
                rebuilt[idx] = f"📻 {_short_reason(best, reason_cap)}"
                break
        core = "\n".join(rebuilt)
        if len(core) <= core_limit:
            return core
        reason_cap -= 12
    return _truncate("\n".join(lines), core_limit)


_STRATEGY_NOTE_RE = re.compile(
    r"([A-Z]{2,4}) pit tendency \((\d+) races\): "
    r"early (\d+)% in pace-competitive stops \((\d+)\), "
    r"cross-team undercut (\d+)% \((\d+) attempts\)",
)


def _constructor_pit_tendency_line(note: str | None, circuit_label: str) -> str | None:
    """
    Observation-only pit tendency line (historical OpenF1 proxies).

    Suppressed unless quali strategist met minimum sample thresholds.
    """
    if not note or not note.strip():
        return None
    m = _STRATEGY_NOTE_RE.search(note)
    if not m:
        return None
    team = m.group(1)
    races = int(m.group(2))
    early_pct = int(m.group(3))
    pace_stops = int(m.group(4))
    undercut_pct = int(m.group(5))
    undercut_attempts = int(m.group(6))
    if races < 3 or pace_stops < 5 or undercut_attempts < 3:
        return None
    place = (circuit_label.split() or ["this circuit"])[0]
    return _truncate(
        f"⚙️ Historical pit trend ({team}): early {early_pct}% "
        f"({pace_stops} pace-competitive stops, {races} races), "
        f"cross-team undercut {undercut_pct}% ({undercut_attempts} attempts) at {place}",
        120,
    )


def _opponent_label_from_reason(reasoning: str) -> str | None:
    m = re.search(r"([A-Za-z0-9 _-]{2,40}) likely holds", reasoning)
    if not m:
        return None
    nick = m.group(1).strip()
    if nick.lower() == "opponent":
        return None
    return nick


def _price_timing_line(best: PickRecommendation) -> str | None:
    if best.price_confidence is None or best.price_confidence <= 0.6 or not best.price_timing_note:
        return None
    mag = best.price_magnitude or 0.0
    if "rising" in best.price_timing_note and "falling" in best.price_timing_note:
        return f"📈 {best.price_timing_note} — in-game prices may shift before lock"
    if best.price_direction == "UP":
        return (
            f"📈 In-game price predicted +${mag:.1f}M next race — "
            "transfer in before price rises in-game"
        )
    if best.price_direction == "DOWN":
        return (
            f"📉 In-game price predicted -${mag:.1f}M next race — "
            "transfer out before price drops in-game"
        )
    return None


def format_personalized_picks(
    weekend: RaceWeekend,
    output: PickOutput,
    *,
    timezone: str,
) -> str:
    """
    Format PATH A personalized pick message (core + mandatory footer).

    Raises:
        AssertionError: If formatted message exceeds total char limit.
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
    price_line = _price_timing_line(best)
    if price_line:
        lines.append(price_line)

    strategy_line = _constructor_pit_tendency_line(
        best.constructor_strategy_note,
        weekend.display_name,
    )
    if strategy_line:
        lines.append(strategy_line)

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
    core = _shrink_core_for_limit(lines, best, PERSONALIZED_MAX_CHARS_CORE)
    return _finalize_pick_broadcast(
        core,
        core_limit=PERSONALIZED_MAX_CHARS_CORE,
        total_limit=PERSONALIZED_MAX_CHARS_TOTAL,
    )


def format_generic_picks(
    weekend: RaceWeekend,
    output: PickOutput,
    *,
    timezone: str,
) -> str:
    """
    Format PATH B generic pick message (core + mandatory footer).

    Raises:
        AssertionError: If formatted message exceeds total char limit.
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
    core = "\n".join(lines)
    if len(core) > GENERIC_MAX_CHARS_CORE:
        trimmed = [lines[0], lines[1]]
        for pick in picks:
            emoji = _confidence_emoji(pick.confidence)
            trimmed.append(
                f"{emoji} {pick.driver_code} — {int(pick.confidence)}% · {_short_reason(pick, 36)}"
            )
        trimmed.extend(lines[-3:])
        core = _truncate("\n".join(trimmed), GENERIC_MAX_CHARS_CORE)
    return _finalize_pick_broadcast(
        core,
        core_limit=GENERIC_MAX_CHARS_CORE,
        total_limit=GENERIC_MAX_CHARS_TOTAL,
    )


def format_recap_message(
    *,
    circuit_name: str,
    correct_count: int,
    total_picks: int,
    season_accuracy_pct: float,
    session_note: str | None,
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
        f"Your GP picks: {correct_count}/{total_picks} correct",
        f"Season GP hit rate: {season_accuracy_pct:.0f}%",
    ]
    if session_note:
        lines.append(session_note)
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


def format_season_recap_message(
    *,
    season: int,
    personalized_accuracy_pct: float,
    community_accuracy_pct: float,
    best_call: str,
    worst_call: str,
    biggest_signal: str,
    share_url: str,
) -> str:
    """Format a user-shareable end-of-season recap artifact."""
    lines = [
        "🏁 Season complete.",
        f"Your GP picks: {personalized_accuracy_pct:.0f}% hit rate (race results)",
        f"PitWallAI community: {community_accuracy_pct:.0f}% hit rate",
        f"Best call: {best_call}",
        f"Worst call: {worst_call}",
        f"Biggest signal this season: {biggest_signal}",
        f"See your full season: {share_url}",
        "",
        "Reply SHARE to get a copy-ready post for any platform.",
    ]
    message = "\n".join(lines)
    message = _truncate(message, SEASON_RECAP_MAX_CHARS)
    assert len(message) <= SEASON_RECAP_MAX_CHARS, (
        f"Season recap message {len(message)} chars exceeds {SEASON_RECAP_MAX_CHARS}"
    )
    return message
