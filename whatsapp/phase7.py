"""Phase 7 competitive value broadcasts and command helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from db.models import FantasyTeam, Subscriber
from intelligence.budget_tracker import format_budget_whatsapp, track_team_value
from fantasy.rules import chip_available
from intelligence.chip_planner import (
    CHIP_TO_CANONICAL,
    ChipType,
    generate_chip_plan,
    persist_chip_plan,
    remaining_races_from_now,
)
from intelligence.counterfactual import generate_counterfactual
from intelligence.repository import (
    get_all_picks_for_race,
    get_draft_picks_for_race,
    get_fantasy_team,
    increment_subscriber_races_received,
    list_active_subscribers,
    load_practice_signals_by_circuit,
    load_season_accuracy_row,
    notification_already_sent,
    record_notification_sent,
)
from intelligence.weekend_picks import generate_picks_for_weekend
from openf1.client import OpenF1Client
from scheduler.calendar import (
    CALENDAR_2026,
    RaceWeekend,
    get_race_weekend,
    get_next_race_weekend,
    profile_circuit_key,
)
from whatsapp.counterfactual_format import (
    format_counterfactual_whatsapp,
    format_share_card_line,
    resolve_next_race,
)
from whatsapp.sender import mask_phone, send_message


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


def _lock_time_local(weekend: RaceWeekend, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    lock = weekend.fantasy_lock_utc.astimezone(tz)
    return lock.strftime("%a %H:%M")


async def broadcast_counterfactual_recaps(race_key: str) -> dict[str, int]:
    """Send post-race counterfactual + share link to subscribers who got picks."""
    from intelligence.repository import list_subscribers_for_race_picks

    subs = await list_subscribers_for_race_picks(race_key)
    sent = failed = 0
    next_name, next_days = resolve_next_race()
    for sub in subs:
        try:
            recap = await generate_counterfactual(sub.phone, race_key)
            body = format_counterfactual_whatsapp(
                recap,
                next_race_name=next_name,
                days_until_next=next_days,
            )
            share = format_share_card_line(recap.share_token)
            await send_message(sub.phone, f"{body}\n{share}")
            await increment_subscriber_races_received(sub.phone)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.error("counterfactual failed phone={}: {}", mask_phone(sub.phone), exc)
    return {"sent": sent, "failed": failed}


async def broadcast_friday_delta(race_key: str, *, app: object, settings: object) -> dict[str, int]:
    """FP2 signal delta — suppressed on sprint weekends (no FP2)."""
    weekend = get_race_weekend(race_key)
    if weekend is None or weekend.is_sprint:
        return {"sent": 0, "skipped": "sprint_weekend"}

    circuit_key = profile_circuit_key(weekend.circuit_key)
    signals = await load_practice_signals_by_circuit(circuit_key)
    by_code = {s.driver_code: s for s in signals}
    subs = await list_active_subscribers()
    sent = 0

    for sub in subs:
        if sub.cadence_preference != "FULL":
            continue
        team = await get_fantasy_team(sub.phone)
        if team is None or team.driver_1 is None:
            continue
        roster = [c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c]
        drafts = await get_draft_picks_for_race(sub.phone, race_key)
        draft_driver = drafts[0].transfer_in or drafts[0].driver_code if drafts else None
        lock = _lock_time_local(weekend, sub.timezone)

        msg: str | None = None
        for code in roster:
            sig = by_code.get(code)
            if sig and sig.anomaly_flags:
                flag = sig.anomaly_flags[0].replace("_", " ")
                pick_ref = draft_driver or code
                msg = _truncate(
                    f"⚠️ FP2 signal update\n\n"
                    f"{code} anomaly flag: {flag}\n"
                    f"Saturday pick still shows {pick_ref} — consider reviewing before lock.\n\n"
                    f"Reply PICKS to see updated recommendations\n"
                    f"Lock: {lock}",
                    280,
                )
                break

        if msg is None:
            for code in roster:
                sig = by_code.get(code)
                if sig and sig.setup_sentiment > 0.45:
                    alt = roster[0] if roster else code
                    msg = _truncate(
                        f"📻 FP2 update: {code} strong practice signal\n\n"
                        f"Radio sentiment {sig.setup_sentiment:+.2f} in FP2.\n"
                        f"Could be worth considering vs your current {alt}.\n\n"
                        f"Reply PICKS to see Saturday recommendations\n"
                        f"Lock: {lock}",
                        280,
                    )
                    break

        if msg is None:
            if (sub.races_received or 0) < 3:
                continue
            msg = _truncate(
                f"✅ {weekend.display_name} FP2 — no major signal changes for your team.\n"
                f"Saturday picks arriving ~3hrs before lock.\n"
                f"Lock: {lock}",
                200,
            )

        try:
            await send_message(sub.phone, msg)
            sent += 1
        except Exception as exc:
            logger.error("friday_delta failed phone={}: {}", mask_phone(sub.phone), exc)
    return {"sent": sent}


async def broadcast_sprint_playbook(race_key: str) -> dict[str, int]:
    """Thursday sprint weekend context for FULL cadence subscribers."""
    from whatsapp.sprint_playbook import format_sprint_playbook_message

    weekend = get_race_weekend(race_key)
    if weekend is None or not weekend.is_sprint:
        return {"sent": 0}
    sent = 0
    for sub in await list_active_subscribers():
        if sub.cadence_preference != "FULL":
            continue
        try:
            msg = await format_sprint_playbook_message(weekend, sub.timezone, phone=sub.phone)
            await send_message(sub.phone, msg)
            sent += 1
        except Exception as exc:
            logger.error("sprint_playbook failed phone={}: {}", mask_phone(sub.phone), exc)
    return {"sent": sent}


async def broadcast_community_aggregate(race_key: str) -> dict[str, int]:
    """Community stats 2hrs after scoring — min 10 picks, skip race 1."""
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return {"sent": 0}
    prior = [w for w in CALENDAR_2026 if w.race_utc < weekend.race_utc]
    if len(prior) < 1:
        return {"sent": 0, "skipped": "first_race"}

    rows = await get_all_picks_for_race(race_key)
    scored = [r for r in rows if r.was_correct is not None and r.pick_status != "draft"]
    if len(scored) < 10:
        return {"sent": 0, "skipped": "insufficient_sample"}

    correct_pct = 100.0 * sum(1 for r in scored if r.was_correct) / len(scored)
    contrarian = [r for r in scored if (r.ownership_tier or "").upper() == "LOW"]
    consensus = [r for r in scored if (r.ownership_tier or "").upper() == "HIGH"]
    contra_delta = (
        sum(float(r.actual_points_delta or 0) for r in contrarian) / len(contrarian)
        if contrarian
        else None
    )
    cons_delta = (
        sum(float(r.actual_points_delta or 0) for r in consensus) / len(consensus)
        if consensus
        else None
    )

    attack_rows = [r for r in scored if (r.league_strategy_applied or "").upper() == "ATTACK"]
    attack_gain = None
    if attack_rows:
        attack_gain = sum(1 for r in attack_rows if r.was_correct) / len(attack_rows)

    by_driver: Counter[str] = Counter()
    for r in scored:
        if r.was_correct:
            by_driver[r.driver_code] += 1
    best_call = by_driver.most_common(1)[0][0] if by_driver else ""

    season = await load_season_accuracy_row(2026)
    season_pct = season.overall_accuracy if season else 0.0
    races_done = len([w for w in CALENDAR_2026 if w.race_utc <= weekend.race_utc])

    lines = [
        f"📊 {weekend.display_name} community results",
        "",
        f"{correct_pct:.0f}% of PitWallAI picks scored this weekend",
    ]
    if contra_delta is not None and cons_delta is not None and contra_delta > cons_delta:
        lines.append(f"Contrarian picks +{contra_delta - cons_delta:.1f}pts vs consensus avg")
    if attack_gain is not None:
        lines.append(f"ATTACK mode: {attack_gain * 100:.0f}% hit rate this weekend")
    lines.append(f"Season: {races_done} races · {season_pct:.0f}% overall GP hit rate")
    lines.append("pitwallai.app/accuracy")
    msg = _truncate("\n".join(lines), 280)

    sent = 0
    for sub in await list_active_subscribers():
        try:
            await send_message(sub.phone, msg)
            sent += 1
        except Exception as exc:
            logger.error("community_aggregate failed phone={}: {}", mask_phone(sub.phone), exc)
    return {"sent": sent}


async def broadcast_banked_transfer_warnings(race_key: str) -> dict[str, int]:
    """Warn subscribers at 3 banked transfers once per weekend."""
    sent = 0
    for sub in await list_active_subscribers():
        team = await get_fantasy_team(sub.phone)
        if team is None or team.remaining_budget is None:
            continue
        if team.transfers_available != 3:
            continue
        if await notification_already_sent(race_key, sub.phone, "banked_transfer_warning"):
            continue
        msg = _truncate(
            "🔄 Transfers: you have 3 banked\n"
            "⚠️ At the cap — new transfers won't accumulate. "
            "Worth reviewing use this weekend.",
            200,
        )
        try:
            await send_message(sub.phone, msg)
            await record_notification_sent(race_key, sub.phone, "banked_transfer_warning")
            sent += 1
        except Exception as exc:
            logger.error("banked_transfer_warning failed phone={}: {}", mask_phone(sub.phone), exc)
    return {"sent": sent}


async def send_picks_on_demand(
    phone: str,
    *,
    client: OpenF1Client,
    app: object,
    settings: object,
) -> str:
    """PICKS command — recommendations through Saturday lock."""
    now = datetime.now(tz=UTC)
    weekend = get_next_race_weekend(after=now)
    if weekend is None:
        return _truncate("No upcoming race on the calendar.")
    if now >= weekend.fantasy_lock_utc:
        nxt = get_next_race_weekend(after=weekend.race_utc)
        name = nxt.display_name if nxt else "TBC"
        days = max(0, (nxt.race_utc - now).days) if nxt else 0
        return _truncate(f"Picks are locked for {weekend.display_name}. Next race: {name} in {days} days.")

    team = await get_fantasy_team(phone)
    output = await generate_picks_for_weekend(
        weekend,
        client=client,
        agent=app.state.agent,
        vector_store=app.state.vector_store,
        settings=settings,
        phone=phone,
        persist_picks=False,
    )
    from whatsapp.message_format import format_generic_picks, format_personalized_picks
    from whatsapp.broadcast import _is_personalized_eligible

    sub = await _subscriber_or_default(phone)
    personalized = _is_personalized_eligible(team)
    if personalized:
        core = format_personalized_picks(weekend, output, timezone=sub.timezone)
    else:
        core = format_generic_picks(weekend, output, timezone=sub.timezone)
    return core


async def send_chips_summary(phone: str) -> str:
    team = await get_fantasy_team(phone)
    if team is None:
        return _truncate("Text TEAM to set up your squad first.")
    plan = generate_chip_plan(team, remaining_races_from_now())
    plan = await persist_chip_plan(phone, plan)
    remaining = len(plan.windows)
    seq_lines = []
    for chip, rk in plan.recommended_sequence[:3]:
        wk = get_race_weekend(rk)
        label = wk.display_name if wk else rk
        seq_lines.append(f"{chip} → {label}")
    seq_txt = "\n".join(seq_lines) if seq_lines else "No unused chips scored highly."
    return _truncate(
        f"🎴 Chip plan for remaining {remaining} races\n\n"
        f"📅 Recommended sequence:\n{seq_txt}\n\n"
        f"Full plan: pitwallai.app/chips/{plan.share_token}\n"
        f"Reply CHIPS LIMITLESS for specific advice",
        300,
    )


async def send_chip_detail(phone: str, chip_raw: str) -> str:
    team = await get_fantasy_team(phone)
    if team is None:
        return _truncate("Text TEAM first.")
    try:
        chip = ChipType(chip_raw.lower())
    except ValueError:
        return _truncate("Try CHIPS LIMITLESS, CHIPS WILDCARD, etc.")
    if not chip_available(team.chips_used or {}, CHIP_TO_CANONICAL[chip]):
        return _truncate(f"{chip.value} chip already used this season.")
    plan = generate_chip_plan(team, remaining_races_from_now())
    matches = [w for w in plan.windows if chip in w.recommended_chips]
    if not matches:
        return _truncate(f"No strong {chip.value} window in remaining races.")
    best = max(matches, key=lambda w: w.confidence)
    return _truncate(
        f"🎴 {chip.value} — {best.race_name}\n"
        f"Confidence {best.confidence:.0%} ({best.priority})\n"
        f"{best.reasoning}\n"
        f"Sprint: {'yes' if best.is_sprint else 'no'}",
        300,
    )


async def send_transfers_status(phone: str) -> str:
    from fantasy.rules import PENALTY_EXTRA_TRANSFER_PTS

    team = await get_fantasy_team(phone)
    if team is None:
        return _truncate("Text TEAM to set up your squad.")
    n = team.transfers_available
    if n == 3:
        return _truncate(
            "🔄 Transfers: you have 3 banked\n"
            "⚠️ At the cap — new transfers won't accumulate. "
            "Consider using one this weekend.",
        )
    if n == 0:
        return _truncate(
            f"🔄 Transfers: you have 0 banked\n"
            f"No transfers banked. Using one this weekend costs "
            f"-{PENALTY_EXTRA_TRANSFER_PTS}pts.",
        )
    return _truncate(
        f"🔄 Transfers: you have {n} banked\n"
        f"{n} available. Each unused banks for next race (max 3).",
    )


async def send_budget_status(phone: str, race_key: str | None = None) -> str:
    team = await get_fantasy_team(phone)
    if team is None:
        return _truncate("Text TEAM first.")
    rk = race_key
    if rk is None:
        w = get_next_race_weekend(after=datetime.now(tz=UTC))
        if w is None:
            return _truncate("No race weekend for budget snapshot.")
        prior = [x for x in CALENDAR_2026 if x.race_utc < w.race_utc]
        rk = prior[-1].race_key if prior else w.race_key
    snap = await track_team_value(phone, rk)
    return format_budget_whatsapp(snap)


async def _subscriber_or_default(phone: str) -> Subscriber:
    from intelligence.repository import get_subscriber

    sub = await get_subscriber(phone)
    if sub:
        return sub
    return Subscriber(phone=phone, timezone="UTC", preferred_provider="gemini", active=True)
