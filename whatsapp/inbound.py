"""Inbound WhatsApp orchestration (onboarding flows + command router)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from loguru import logger

from intelligence.repository import (
    add_user_reported_price_change,
    erase_subscriber_data,
    get_league_onboarding_state,
    get_onboarding_state,
    get_price_prediction_map,
    set_subscriber_share_private,
    update_subscriber_preferences,
)
from intelligence.season_recap import build_season_recap
from pitwallai.feature_flags import (
    budget_transfers_enabled,
    chips_enabled,
    constructor_strategy_enabled,
    season_recap_enabled,
)
from scheduler.calendar import CALENDAR_2026, get_next_race_weekend
from scheduler.context import get_current_race_key
from whatsapp.command_router import route
from whatsapp.league_flow import handle_league_command
from whatsapp.message_format import format_season_recap_message
from whatsapp.sender import mask_phone, send_message as _send_message
from whatsapp.subscribe_flow import (
    clear_pending_timezone,
    complete_subscribe,
    handle_subscribe,
    handle_unsubscribe,
    is_pending_timezone,
    truncate,
)
from whatsapp.team_flow import handle_team_command

_SETTINGS_URL = "https://pitwallai.app/settings"
_SEASON_SHARE_BASE_URL = "https://pitwallai.app"

def _last_race_key() -> str | None:
    now = datetime.now(tz=UTC)
    completed = [w for w in CALENDAR_2026 if w.race_utc <= now]
    if not completed:
        return None
    return max(completed, key=lambda w: w.race_utc).race_key


def _next_race_key() -> str | None:
    nxt = get_next_race_weekend(after=datetime.now(tz=UTC))
    return nxt.race_key if nxt else None


async def _handle_delete(phone: str) -> str:
    deleted = await erase_subscriber_data(phone)
    await clear_pending_timezone(phone)
    if deleted:
        logger.bind(phone=mask_phone(phone)).info("Subscriber data erased (DELETE command)")
    return truncate(
        "✅ All your data has been deleted. Sorry to see you go. "
        "Text SUBSCRIBE anytime to rejoin."
    )


def _handle_settings() -> str:
    return truncate(f"Manage API keys & provider: {_SETTINGS_URL}")


async def _handle_live(phone: str, *, enabled: bool) -> str:
    row = await update_subscriber_preferences(phone, live_alerts=enabled)
    if row is None:
        return truncate("Subscribe first: text SUBSCRIBE")
    if enabled:
        return truncate("✅ Race day alerts on. You'll get live updates during Sunday's race.")
    return truncate("✅ Race day alerts off. Picks only.")


async def _handle_cadence(phone: str, *, mode: str) -> str:
    row = await update_subscriber_preferences(phone, cadence_preference=mode)
    if row is None:
        return truncate("Subscribe first: text SUBSCRIBE")
    if mode == "FULL":
        return truncate(
            "✅ Full weekend mode. Practice summary, quali picks, live alerts, post-race recap."
        )
    return truncate("✅ Race day only. Saturday picks and live alerts (if LIVE ON).")


async def _handle_price_report(phone: str, raw_text: str) -> str:
    parts = raw_text.strip().split()
    if len(parts) != 3:
        return truncate("Use: PRICE NOR +0.2")
    _, code, delta_raw = parts
    code = code.strip().upper()
    try:
        delta = float(delta_raw)
    except ValueError:
        return truncate("Use numeric change like +0.2 or -0.1")
    race_key = _last_race_key()
    if race_key is None:
        return truncate("No completed race found yet for price reports.")
    await add_user_reported_price_change(
        driver_code=code,
        race_key=race_key,
        reported_change=delta,
        reporter_phone=phone,
    )
    return truncate("Thanks! Helps improve predictions.")


async def _handle_why_constructor(code: str) -> str:
    from circuits.profiles import get_circuit_profile
    from intelligence.repository import load_constructor_strategy_profile
    from scheduler.calendar import get_race_weekend, profile_circuit_key

    code = code.strip().upper()
    race_key = _next_race_key()
    if race_key is None:
        return truncate("No upcoming race found.")
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return truncate("No upcoming race found.")
    circuit_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(circuit_key)
    circuit_label = circuit.display_name if circuit else circuit_key.replace("_", " ").title()
    profile = await load_constructor_strategy_profile(code, circuit_key)
    if profile is None:
        return truncate(f"No strategy data for {code} at {circuit_label} yet.")
    early = int(round(profile.early_box_rate * 100))
    undercut = profile.undercut_attempt_rate
    undercut_pct = int(round(undercut * 100)) if undercut is not None else "n/a"
    sc_pct = int(round(profile.safety_car_opportunist * 100))
    n = profile.sample_size
    msg = (
        f"🏭 {code} at {circuit_label}\n"
        f"Early box: {early}% ({n} races) · Undercut: {undercut_pct}% · SC: {sc_pct}%\n"
        f"Fantasy: {profile.fantasy_tendency}\n"
        f"Quality: {profile.data_quality} · {n} races"
    )
    if profile.data_quality == "LOW":
        msg += "\n⚠️ Limited data — treat with caution."
    return truncate(msg, limit=280)


async def _handle_why(raw_text: str) -> str:
    parts = raw_text.strip().split()
    if len(parts) >= 3 and parts[1].upper() == "CONSTRUCTOR":
        if not constructor_strategy_enabled():
            return truncate("Constructor strategy is off-bet for now. Reply HELP for current commands.")
        return await _handle_why_constructor(parts[2])
    if len(parts) != 2:
        return truncate("Use: WHY NOR or WHY CONSTRUCTOR FER")
    _, code = parts
    code = code.strip().upper()
    race_key = _next_race_key()
    if race_key is None:
        return truncate("No upcoming race found.")
    preds = await get_price_prediction_map(race_key)
    pred = preds.get(code)
    if pred is None:
        # No persisted prediction yet (e.g. before the Saturday pipeline, or in
        # the live simulator) — compute one on the fly from current signals so
        # each driver gets a real, differentiated breakdown.
        from intelligence.price_predictor import predict_price_changes
        from intelligence.signal_cache import circuit_key_for_race

        circuit_key = circuit_key_for_race(race_key)
        if circuit_key is not None:
            computed = await predict_price_changes(race_key, circuit_key)
            pred = next((p for p in computed if p.driver_code == code), None)
    if pred is None:
        return truncate(f"No prediction yet for {code}.")

    lines: list[str] = []
    standing = await _practice_standing_line(race_key, code)
    if standing:
        lines.append(standing)

    bd = pred.signal_breakdown or {}
    lines.append(
        f"{code}: price likely {pred.predicted_direction} "
        f"(${pred.predicted_magnitude:.1f}M), conf {pred.confidence:.2f}"
    )
    # Only show the signal breakdown when something actually fired. Early in the
    # season the price-move signals (form momentum, ownership, circuit history)
    # have little data, so a wall of "+0.00" reads as broken rather than honest.
    drivers_seg = []
    for key in ("momentum", "value_ratio", "circuit_hist", "practice_align", "ownership_pressure"):
        seg = bd.get(key) or {}
        if not seg:
            continue
        if abs(float(seg.get("score", 0))) < 0.01:
            continue
        drivers_seg.append(f"{key} {seg.get('score', 0):+.2f}")
    if drivers_seg:
        lines.append("Drivers of the move: " + ", ".join(drivers_seg))
    else:
        lines.append("Price-move signals (form, ownership, circuit history) build up over the season.")

    from intelligence.llm_insight import driver_name, llm_tip

    insight = await llm_tip(
        f"Driver {driver_name(code)}. {standing or ''} "
        f"Price outlook: {pred.predicted_direction} (${pred.predicted_magnitude:.1f}M), "
        f"confidence {pred.confidence:.2f}.",
        allowed_codes={code.upper()},
    )
    if insight:
        lines.append(f"💡 {insight}")
    return truncate("\n".join(lines), limit=500)


_GRADE_CHIP_WORDS: dict[str, str] = {
    "limitless": "limitless",
    "wildcard": "wildcard",
    "no negative": "no_negative",
    "no_negative": "no_negative",
    "nonegative": "no_negative",
    "extra drs": "extra_drs",
    "3x": "extra_drs",
    "final fix": "final_fix",
    "autopilot": "autopilot",
}


def _extract_lineup(raw_text: str) -> tuple[list[str], list[str], str | None]:
    """Pull driver codes, constructor codes and a chip from free text."""
    from fantasy.rules import CONSTRUCTOR_PRICES_M, DRIVER_PRICES_M

    upper = raw_text.upper()
    tokens = re.findall(r"\b[A-Z]{2,3}\b", upper)
    drivers: list[str] = []
    constructors: list[str] = []
    for tok in tokens:
        if tok in DRIVER_PRICES_M and tok not in drivers:
            drivers.append(tok)
        elif tok in CONSTRUCTOR_PRICES_M and tok not in constructors:
            constructors.append(tok)
    low = raw_text.lower()
    chip = next((c for word, c in _GRADE_CHIP_WORDS.items() if word in low), None)
    return drivers, constructors, chip


def _extract_captain(raw_text: str, drivers: list[str]) -> str | None:
    """Find a stated captain among the lineup's drivers ('captain HAM', 'HAM (c)')."""
    upper = raw_text.upper()
    patterns = [
        r"(?:CAPTAIN|CAPTAINING|TRIPLE|TRIPLING|\(C\))\s+([A-Z]{2,3})",
        r"\b([A-Z]{2,3})\s+(?:AS\s+)?(?:CAPTAIN|\(C\))",
    ]
    for pat in patterns:
        for m in re.findall(pat, upper):
            if m in drivers:
                return m
    return None


async def _handle_grade(raw_text: str) -> str:
    """Grade a stated lineup (drivers + constructors + chip) vs PitWallAI."""
    body = raw_text
    if body.upper().startswith("GRADE"):
        body = body[5:]
    drivers, constructors, chip = _extract_lineup(body)
    if len(drivers) < 1:
        return truncate(
            "Tell me your lineup to grade, e.g.\n"
            "GRADE HAM, LEC, ANT, RUS, VER and MER, FER with limitless, captain HAM",
            limit=200,
        )
    captain = _extract_captain(body, drivers)
    race_key = _next_race_key()
    if race_key is None:
        return truncate("No upcoming race to grade against.")

    from intelligence.lineup_grader import grade_lineup, grade_lineup_facts

    msg = await grade_lineup(race_key, drivers, constructors, chip, captain)

    facts, allowed = await grade_lineup_facts(race_key, drivers, constructors, chip, captain)
    if facts:
        from intelligence.llm_insight import llm_tip

        verdict = await llm_tip(
            facts + " In one sentence, judge how this lineup compares to the model's top picks.",
            allowed_codes=allowed,
        )
        if verdict:
            msg = f"{msg}\n\n💡 {verdict}"
    return truncate(msg, limit=900)


async def _handle_lock(phone: str, raw_text: str) -> str:
    """Commit a stated lineup for the upcoming race so it can be scored later."""
    body = raw_text
    for prefix in ("LOCK IN", "LOCK"):
        if body.upper().startswith(prefix):
            body = body[len(prefix):]
            break
    drivers, constructors, chip = _extract_lineup(body)
    if len(drivers) < 1:
        return truncate(
            "Tell me the lineup to lock, e.g.\n"
            "LOCK HAM, LEC, ANT, RUS, VER and MER, FER with limitless, captain HAM",
            limit=200,
        )
    captain = _extract_captain(body, drivers)
    race_key = _next_race_key()
    if race_key is None:
        return truncate("No upcoming race to lock for.")

    from intelligence.lineup_grader import model_top_picks
    from intelligence.repository import save_locked_lineup
    from scheduler.calendar import get_race_weekend

    m_drivers, m_cons, m_cap = await model_top_picks(race_key)
    await save_locked_lineup(
        phone=phone,
        race_key=race_key,
        drivers=drivers,
        constructors=constructors,
        chip=chip,
        captain=captain,
        model_drivers=m_drivers,
        model_constructors=m_cons,
        model_captain=m_cap,
    )
    wk = get_race_weekend(race_key)
    name = wk.display_name if wk else race_key
    cap_txt = f" · captain {captain}" if captain else ""
    chip_txt = f" · {chip}" if chip else ""
    lines = [
        f"🔒 Locked your {name} call.",
        f"You: {', '.join(drivers)} | {', '.join(constructors)}{cap_txt}{chip_txt}",
        f"🤖 My pick: {', '.join(m_drivers)} | {', '.join(m_cons)} · captain {m_cap or '—'}",
        "",
        "I'll score both against the result. Text SCORE after the race.",
    ]
    return truncate("\n".join(lines), limit=500)


def _resolve_race_key(text: str) -> str | None:
    """Find a race in free text by circuit key or a word from its name."""
    from scheduler.calendar import CALENDAR_2026

    aliases: dict[str, str] = {}
    for w in CALENDAR_2026:
        aliases[w.circuit_key] = w.race_key
        for word in w.display_name.lower().replace("-", " ").split():
            if word not in {"grand", "prix"} and len(word) > 3:
                aliases.setdefault(word, w.race_key)
    low = text.lower()
    for alias, rk in aliases.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            return rk
    return None


async def _handle_score(phone: str, raw_text: str) -> str:
    """Score a stated or locked lineup vs PitWallAI vs the actual result."""
    from intelligence.lineup_grader import (
        model_top_picks,
        perfect_lineup_from_positions,
        score_against_result,
    )
    from intelligence.repository import get_locked_lineup
    from scheduler.calendar import get_race_weekend

    body = raw_text[5:] if raw_text.upper().startswith("SCORE") else raw_text
    drivers, constructors, chip = _extract_lineup(body)
    captain = _extract_captain(body, drivers) if drivers else None
    race_key = _resolve_race_key(body) or _next_race_key()
    if race_key is None:
        return truncate("No race to score against.")

    if drivers:
        m_drivers, m_cons, m_cap = await model_top_picks(race_key)
    else:
        locked = await get_locked_lineup(phone, race_key)
        if locked is None:
            return truncate(
                "Nothing locked for this race. Text LOCK <lineup>, or "
                "SCORE <lineup> at <race> to grade against any past race."
            )
        drivers, constructors, chip, captain = (
            locked.drivers, locked.constructors, locked.chip, locked.captain
        )
        m_drivers, m_cons, m_cap = locked.model_drivers, locked.model_constructors, locked.model_captain

    you = await score_against_result(race_key, drivers, constructors, chip, captain)
    if you is None:
        wk = get_race_weekend(race_key)
        name = wk.display_name if wk else race_key
        return truncate(f"{name} hasn't been classified yet — I'll score it after the flag.")

    model = (
        await score_against_result(race_key, m_drivers, m_cons, chip, m_cap) if m_drivers else None
    )
    perfect = perfect_lineup_from_positions(you["positions"])
    you_t, perfect_t = you["total"], (perfect["total"] or 1)
    capture = round(100 * you_t / perfect_t)

    def _pos(code: str) -> str:
        p = you["positions"].get(code)
        return f"P{p}" if p else "DNF"

    from intelligence.repository import record_lineup_score

    await record_lineup_score(
        phone=phone,
        race_key=race_key,
        drivers=drivers,
        constructors=constructors,
        chip=chip,
        captain=you["captain"],
        your_points=you_t,
        model_points=(model["total"] if model is not None else None),
        perfect_points=perfect["total"],
        capture_pct=capture,
    )

    your_drivers = " · ".join(f"{d} {_pos(d)} {p}" for d, p in you["driver_pts"].items())
    wk = get_race_weekend(race_key)
    lines = [f"🏁 {wk.display_name if wk else race_key} — scored:"]
    lines.append(f"  You:       {you_t} pts (captain {you['captain']} +{you['captain_bonus']})")
    if model is not None:
        model_t = model["total"]
        verdict = (
            "you beat PitWallAI! 🏆" if you_t > model_t
            else "PitWallAI edged it." if model_t > you_t else "dead heat."
        )
        lines.append(f"  PitWallAI: {model_t} pts")
    else:
        verdict = ""
    lines.append(f"  Perfect:   {perfect_t} pts ({', '.join(perfect['drivers'])})")
    lines.append(f"→ {verdict} You captured {capture}% of the ceiling.".strip())
    lines.append("")
    lines.append(f"Your drivers: {your_drivers}")
    return truncate("\n".join(lines), limit=650)


async def _handle_record(phone: str) -> str:
    """Season scorecard: your record vs PitWallAI and avg ceiling capture."""
    from intelligence.repository import list_scored_lineups
    from scheduler.calendar import get_race_weekend

    rows = await list_scored_lineups(phone)
    if not rows:
        return truncate(
            "No scored races yet. Try `SCORE <lineup> at <race>` to backtest, "
            "or LOCK a lineup and SCORE it after the race."
        )

    def _name(rk: str) -> str:
        wk = get_race_weekend(rk)
        return wk.display_name.replace(" Grand Prix", "") if wk else rk

    caps = [r.capture_pct for r in rows if r.capture_pct is not None]
    avg_cap = round(sum(caps) / len(caps)) if caps else 0
    vs_model = [(r.your_points, r.model_points) for r in rows if r.model_points is not None]
    wins = sum(1 for y, m in vs_model if y > m)
    losses = sum(1 for y, m in vs_model if m > y)
    ties = sum(1 for y, m in vs_model if y == m)
    best = max(rows, key=lambda r: r.capture_pct or 0)
    worst = min(rows, key=lambda r: r.capture_pct or 0)

    lines = [
        f"📈 Your PitWallAI scorecard — {len(rows)} race(s)",
        f"🎯 Avg ceiling capture: {avg_cap}%",
    ]
    if vs_model:
        rec = f"{wins}-{losses}" + (f"-{ties}" if ties else "")
        lines.append(f"🤖 vs PitWallAI: {rec}")
    lines.append(f"🏆 Best: {_name(best.race_key)} {best.capture_pct}%")
    if worst.race_key != best.race_key:
        lines.append(f"🧊 Worst: {_name(worst.race_key)} {worst.capture_pct}%")
    return truncate("\n".join(lines), limit=400)


async def _practice_standing_line(race_key: str, code: str) -> str | None:
    """One-line live practice standing for a driver (rank, pace, flags)."""
    from intelligence.signal_cache import load_practice_by_driver, circuit_key_for_race

    circuit_key = circuit_key_for_race(race_key)
    if circuit_key is None:
        return None
    by_driver = await load_practice_by_driver(circuit_key)
    sig = by_driver.get(code.upper())
    if sig is None:
        return None
    # Practice position = rank by pace_satisfaction across all drivers seen.
    ranked = sorted(by_driver.values(), key=lambda s: s.pace_satisfaction, reverse=True)
    pos = next((i for i, s in enumerate(ranked, start=1) if s.driver_code == code.upper()), None)
    pace_pct = int(round(sig.pace_satisfaction * 100))
    flags = ", ".join(sig.anomaly_flags) if sig.anomaly_flags else "clean run"
    pos_txt = f"P{pos} on practice pace" if pos else "practice pace"
    return f"📻 {code}: {sig.session} {pos_txt} ({pace_pct}% pace index) · {flags}"


def _season_share_secret() -> str:
    from whatsapp.settings import get_whatsapp_settings

    settings = get_whatsapp_settings()
    if settings.whatsapp_app_secret.strip():
        return settings.whatsapp_app_secret.strip()
    if settings.webhook_verify_token.strip():
        return settings.webhook_verify_token.strip()
    return "pitwallai-season-share-local-secret"


async def _handle_season(phone: str, *, compact: bool = False) -> str:
    recap = await build_season_recap(
        phone=phone,
        season=2026,
        share_base_url=_SEASON_SHARE_BASE_URL,
        share_secret=_season_share_secret(),
    )
    message = format_season_recap_message(
        season=recap.season,
        personalized_accuracy_pct=recap.personalized_accuracy_pct,
        community_accuracy_pct=recap.community_accuracy_pct,
        best_call=recap.best_call,
        worst_call=recap.worst_call,
        biggest_signal=recap.biggest_signal,
        share_url=recap.share_url,
    )
    if not compact:
        return message
    return "\n".join(
        [
            "🏁 PitWallAI season recap",
            f"My GP picks: {recap.personalized_accuracy_pct:.0f}% hit rate (race results)",
            f"Community GP hit rate: {recap.community_accuracy_pct:.0f}%",
            f"Best call: {recap.best_call}",
            f"Worst call: {recap.worst_call}",
            f"Biggest signal: {recap.biggest_signal}",
            recap.share_url,
        ]
    )


async def handle_inbound_text(phone: str, text: str, raw_text: str) -> None:
    """
    Route inbound WhatsApp text: onboarding flows, legacy commands, then router.

    Sends the response via Meta Cloud API. Swallows send errors after logging.
    """
    from onboarding.rehearsal import notify_rehearsal_user_activity

    notify_rehearsal_user_activity(phone)
    reply: str | list[str]

    try:
        onboarding = await get_onboarding_state(phone)
        league_state = await get_league_onboarding_state(phone)
        in_team_flow = onboarding is not None and (
            onboarding.awaiting_confirm or onboarding.step > 0
        )
        in_league_flow = league_state is not None and (
            league_state.awaiting_confirm or league_state.step > 0 or league_state.update_mode
        )

        pending_tz = await is_pending_timezone(phone)

        # Natural-language intent: let users type "should I play a chip" instead
        # of CHIPS. Only outside data-entry flows (team/league/timezone), where
        # free text is structured input rather than a request.
        if not (in_team_flow or in_league_flow or pending_tz):
            from whatsapp.intent import resolve_intent_smart

            canonical = await resolve_intent_smart(raw_text)
            if canonical is not None:
                text = canonical
                raw_text = canonical

        if pending_tz and text not in {
            "SUBSCRIBE",
            "UNSUBSCRIBE",
            "DELETE",
            "HELP",
            "SETTINGS",
            "TEAM",
        }:
            reply = await complete_subscribe(phone, raw_text)
        elif text.startswith("TIMEZONE "):
            reply = await complete_subscribe(phone, raw_text[9:].strip())
        elif in_team_flow and text != "TEAM":
            reply = await handle_team_command(phone, text, raw_text)
        elif in_league_flow and text not in {"LEAGUE", "LEAGUE UPDATE"}:
            reply = await handle_league_command(phone, text, raw_text)
        elif text == "TEAM":
            reply = await handle_team_command(phone, text, raw_text)
        elif text in {"LEAGUE", "LEAGUE UPDATE"}:
            reply = await handle_league_command(phone, text, raw_text)
        elif text.startswith("UPDATE "):
            from whatsapp.commands.update import handle_update

            reply = await handle_update(phone, raw_text)
        elif text.startswith("PRICE "):
            reply = await _handle_price_report(phone, raw_text)
        elif text.startswith("WHY "):
            reply = await _handle_why(raw_text)
        elif text.startswith("GRADE"):
            reply = await _handle_grade(raw_text)
        elif text.startswith("LOCK"):
            reply = await _handle_lock(phone, raw_text)
        elif text.startswith("SCORE"):
            reply = await _handle_score(phone, raw_text)
        elif text == "RECORD":
            reply = await _handle_record(phone)
        elif text == "SEASON":
            if not season_recap_enabled():
                reply = truncate("Season recap isn't live yet. Reply HELP for available commands.")
            else:
                reply = await _handle_season(phone, compact=False)
        elif text.startswith("SHARE "):
            from whatsapp.commands.share import handle_share

            parts = raw_text.strip().split()
            code = parts[1] if len(parts) >= 2 else ""
            reply = await handle_share(
                driver_code=code,
                phone_number=phone,
                race_key=_next_race_key() or _last_race_key() or "",
            )
        elif text == "SUBSCRIBE":
            reply = await handle_subscribe(phone)
        elif text == "UNSUBSCRIBE":
            reply = await handle_unsubscribe(phone)
        elif text == "DELETE":
            reply = await _handle_delete(phone)
        elif text == "SETTINGS":
            reply = _handle_settings()
        elif text == "LIVE ON":
            reply = await _handle_live(phone, enabled=True)
        elif text == "LIVE OFF":
            reply = await _handle_live(phone, enabled=False)
        elif text == "CADENCE FULL":
            reply = await _handle_cadence(phone, mode="FULL")
        elif text in {"CADENCE RACEDAY", "CADENCE RACE_DAY_ONLY"}:
            reply = await _handle_cadence(phone, mode="RACE_DAY_ONLY")
        elif text == "CHIPS" and chips_enabled():
            from whatsapp.phase7 import send_chips_summary

            reply = await send_chips_summary(phone)
        elif text.startswith("CHIPS ") and chips_enabled():
            from whatsapp.phase7 import send_chip_detail

            chip = raw_text.strip().split(maxsplit=1)[1] if len(raw_text.split()) > 1 else ""
            reply = await send_chip_detail(phone, chip)
        elif text == "CHIPS" or text.startswith("CHIPS "):
            reply = truncate(
                "Chip planner isn't available yet. Reply HELP for supported commands."
            )
        elif text == "TRANSFERS" and budget_transfers_enabled():
            from whatsapp.phase7 import send_transfers_status

            reply = await send_transfers_status(phone)
        elif text == "BUDGET" and budget_transfers_enabled():
            from whatsapp.phase7 import send_budget_status

            reply = await send_budget_status(phone)
        elif text == "PRIVATE":
            await set_subscriber_share_private(phone, private=True)
            reply = truncate("Share cards set to private. Future recaps won't be public links.")
        else:
            reply = await route(raw_text, phone, get_current_race_key())
    except ValueError as exc:
        logger.error("Command handler config error phone={}: {}", mask_phone(phone), exc)
        reply = truncate("Service unavailable. Try again later.")
    except Exception as exc:
        logger.exception("Command handler error phone={}: {}", mask_phone(phone), exc)
        reply = truncate("Something went wrong. Send HELP or try later.")

    try:
        messages = reply if isinstance(reply, list) else [reply]
        for message in messages:
            await _send_message(phone, message)
    except Exception as exc:
        logger.error("Failed to send WhatsApp reply phone={}: {}", mask_phone(phone), exc)
