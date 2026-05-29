"""Agent 5 — Scorer and Signal Quality Learner."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from loguru import logger

from agents.base import AgentRunDependencies
from intelligence.drivers import driver_code_for
from intelligence.repository import (
    get_price_prediction_map,
    get_picks_for_race,
    get_user_reported_price_changes,
    list_subscribers_for_race_picks,
    get_all_picks_for_race,
    load_practice_signals_by_circuit,
    update_pick_result,
    upsert_season_accuracy,
    upsert_signal_quality_row,
    update_price_prediction_actuals,
)
from intelligence.season_recap import build_season_recap
from intelligence.scorer import _fetch_final_positions, _points_for_position
from openf1.client import OpenF1Client
from whatsapp.sender import mask_phone
from orchestrator.race_context import (
    SignalQuality,
    SignalQualityEntry,
    evolve_race_context,
    RaceContext,
)
from intelligence.recap_metrics import hit_rate_pct, momentum_suffix, prev_race_key, session_quality_note
from scheduler.calendar import get_next_race_weekend, get_race_weekend, profile_circuit_key
from circuits.profiles import get_circuit_profile
from whatsapp.message_format import format_recap_message
from whatsapp.sender import mask_phone, send_message


async def get_actual_price_changes(race_key: str) -> dict[str, float]:
    """
    Resolve actual price changes from crowdsourced reports.

    Confirms a driver when >=3 reports are within 0.1M of each other.
    """
    reports = await get_user_reported_price_changes(race_key)
    by_driver: dict[str, list[float]] = defaultdict(list)
    for r in reports:
        by_driver[r.driver_code].append(float(r.reported_change))
    confirmed: dict[str, float] = {}
    for code, vals in by_driver.items():
        vals = sorted(vals)
        if len(vals) < 3:
            continue
        for i in range(0, len(vals) - 2):
            window = vals[i : i + 3]
            if max(window) - min(window) <= 0.1:
                confirmed[code] = round(sum(window) / len(window), 2)
                logger.info("Price change confirmed by {} reporters for {}", len(vals), code)
                break
    return confirmed

def _score_personalized_pick(pick, positions: dict[str, int]) -> tuple[float, bool]:
    in_code = pick.transfer_in or pick.driver_code
    out_code = pick.transfer_out
    in_pts = _points_for_position(positions.get(in_code))
    if out_code:
        out_pts = _points_for_position(positions.get(out_code))
        delta = in_pts - out_pts
        return delta, delta > 0
    pos = positions.get(in_code, 99)
    return in_pts, pos <= 10


def _score_generic_pick(pick, positions: dict[str, int]) -> tuple[float, bool]:
    pos = positions.get(pick.driver_code)
    pts = _points_for_position(pos)
    return pts, pos is not None and pos <= 10


async def _update_signal_quality(
    ctx: RaceContext,
    picks: list,
    positions: dict[str, int],
) -> SignalQuality:
    """Compute hit rates and weight multipliers for next race."""
    circuit_key = ctx.race_weekend.circuit_key
    profile_key = profile_circuit_key(circuit_key)

    practice_rows = await load_practice_signals_by_circuit(profile_key)
    sentiment_hits = 0
    sentiment_total = 0
    for row in practice_rows:
        if row.setup_sentiment <= 0.6:
            continue
        sentiment_total += 1
        pos = positions.get(row.driver_code, 99)
        if pos <= 10:
            sentiment_hits += 1

    sentiment_rate = sentiment_hits / sentiment_total if sentiment_total else 0.5

    anomaly_hits = 0
    anomaly_total = 0
    for row in practice_rows:
        if not row.anomaly_flags:
            continue
        anomaly_total += 1
        pos = positions.get(row.driver_code, 99)
        grid_penalty = pos > 12
        if grid_penalty:
            anomaly_hits += 1
    anomaly_rate = anomaly_hits / anomaly_total if anomaly_total else 0.5

    contrarian_rows = [p for p in picks if bool(getattr(p, "is_contrarian", False))]
    contrarian_total = len(contrarian_rows)
    contrarian_hits = sum(1 for p in contrarian_rows if (p.actual_points_delta or 0.0) > 0.0)
    contrarian_rate = contrarian_hits / contrarian_total if contrarian_total else 0.5

    non_conflict_rows = [p for p in picks if getattr(p, "opponent_conflict", None) is False]
    non_conflict_total = len(non_conflict_rows)
    non_conflict_hits = sum(1 for p in non_conflict_rows if (p.actual_points_delta or 0.0) > 0.0)
    non_conflict_rate = non_conflict_hits / non_conflict_total if non_conflict_total else 0.5

    entries: dict[str, SignalQualityEntry] = {}
    for signal_type, rate in (
        ("practice_sentiment", sentiment_rate),
        ("anomaly_teammate_gap", anomaly_rate),
        ("contrarian_low_ownership", contrarian_rate),
        ("opponent_conflict_avoidance", non_conflict_rate),
    ):
        await upsert_signal_quality_row(circuit_key, signal_type, rate)
        mult = 1.3 if rate > 0.7 else (0.5 if rate < 0.4 else 1.0)
        if signal_type == "contrarian_low_ownership":
            if rate > 0.65:
                mult = 1.4
            elif rate < 0.35:
                mult = 0.7
        mult = max(0.1, min(2.0, mult))
        logger.bind(circuit=circuit_key, signal=signal_type, rate=rate, weight=mult).info(
            "Signal weight adjustment"
        )
        entries[signal_type] = SignalQualityEntry(
            circuit_key=circuit_key,
            signal_type=signal_type,
            sample_size=anomaly_total or sentiment_total,
            hit_rate=rate,
            weight_multiplier=mult,
        )

    note_parts: list[str] = []
    if sentiment_total and sentiment_rate >= 0.66:
        note_parts.append(f"📈 Practice sentiment was {sentiment_hits}/{sentiment_total} this weekend")
    elif sentiment_total and sentiment_rate < 0.34:
        note_parts.append("📉 Practice signals missed — adjusting model")

    return SignalQuality(
        entries=entries,
        practice_sentiment_accuracy=sentiment_rate,
        anomaly_flag_accuracy=anomaly_rate,
        quality_note=" ".join(note_parts)[:50] if note_parts else None,
    )


async def _compute_season_stats(season: int) -> tuple[float, float, float, str, str]:
    from sqlalchemy import select
    from db.models import PickRow
    from db.session import get_session

    prefix = f"{season}_"
    async with get_session() as session:
        result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{prefix}%"),
                PickRow.was_correct.is_not(None),
            )
        )
        rows = list(result.scalars().all())

    if not rows:
        return 0.0, 0.0, 0.0, "n/a", "n/a"

    def acc(subset: list) -> float:
        return 100.0 * sum(1 for r in subset if r.was_correct) / len(subset)

    overall = acc(rows)
    personalized = acc([r for r in rows if r.personalized])
    generic = acc([r for r in rows if not r.personalized])
    by_circuit: dict[str, list] = defaultdict(list)
    for r in rows:
        by_circuit[r.circuit_key].append(r)
    circuit_acc = {k: acc(v) for k, v in by_circuit.items()}
    best = max(circuit_acc, key=circuit_acc.get) if circuit_acc else "n/a"
    worst = min(circuit_acc, key=circuit_acc.get) if circuit_acc else "n/a"
    return overall, personalized, generic, best, worst


async def run_scorer_and_learner(
    ctx: RaceContext,
    deps: AgentRunDependencies,
) -> RaceContext:
    """Score picks, update signal quality, broadcast recap."""
    race_key = ctx.race_weekend.race_key
    weekend = get_race_weekend(race_key)
    if weekend is None:
        return ctx

    profile_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        return ctx

    client = deps.openf1_client
    race_sk = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Race",
    )
    if race_sk is None:
        logger.error("Cannot score — no race session race_key={}", race_key)
        return ctx

    positions = await _fetch_final_positions(client, race_sk)
    picks = await get_all_picks_for_race(race_key)

    for pick in picks:
        if pick.personalized:
            delta, correct = _score_personalized_pick(pick, positions)
        else:
            delta, correct = _score_generic_pick(pick, positions)
        await update_pick_result(pick.id, actual_points_delta=delta, was_correct=correct)

    # Refresh from DB so was_correct/actual_points_delta are populated for the eval pass.
    try:
        from intelligence.eval.runner import compute_eval_report, log_eval_report
        from intelligence.repository import get_prior_season_circuit_winners

        scored_picks = await get_all_picks_for_race(race_key)
        prior_winners = await get_prior_season_circuit_winners(season=2025)
        report = compute_eval_report(
            race_key=race_key,
            circuit_key=profile_key,
            picks=scored_picks,
            positions=positions,
            prior_winners=prior_winners,
        )
        log_eval_report(report)
    except Exception as exc:  # eval is additive — never block scoring
        logger.warning("eval_report skipped race_key={}: {}", race_key, exc)

    overall, pers, gen, best, worst = await _compute_season_stats(2026)
    await upsert_season_accuracy(
        season=2026,
        overall_accuracy=overall,
        personalized_accuracy=pers,
        generic_accuracy=gen,
        best_circuit=best,
        worst_circuit=worst,
    )

    signal_quality = await _update_signal_quality(ctx, picks, positions)
    actual_price_changes = await get_actual_price_changes(race_key)
    if actual_price_changes:
        updated = await update_price_prediction_actuals(race_key=race_key, actuals=actual_price_changes)
        pred_map = await get_price_prediction_map(race_key)
        scored = [p for p in pred_map.values() if p.was_correct is not None]
        if scored:
            hit_rate = sum(1 for p in scored if p.was_correct) / len(scored)
            await upsert_signal_quality_row(ctx.race_weekend.circuit_key, "price_direction_prediction", hit_rate)
            logger.info("Price prediction scored race_key={} updated={} hit_rate={:.2f}", race_key, updated, hit_rate)
    new_ctx = evolve_race_context(ctx, signal_quality=signal_quality)

    from intelligence.constructor_strategy import (
        CONSTRUCTOR_CODES,
        fetch_pit_history,
        update_constructor_profile,
    )

    circuit_key = ctx.circuit_profile.circuit_key
    race_year = ctx.race_weekend.race_utc.year
    for constructor_code in CONSTRUCTOR_CODES:
        try:
            new_events = await fetch_pit_history(
                circuit_key,
                constructor_code,
                years=[race_year],
            )
            await update_constructor_profile(
                constructor_code=constructor_code,
                circuit_key=circuit_key,
                new_pit_events=new_events,
            )
        except Exception as exc:
            logger.warning(
                "constructor profile update failed {} {}: {}",
                constructor_code,
                circuit_key,
                exc,
            )

    from intelligence.budget_tracker import track_team_value
    from sharing.share_cards import generate_share_card

    phones = {p.phone for p in picks if p.phone}
    for phone in phones:
        try:
            await generate_share_card(phone, race_key)
            await track_team_value(phone, race_key)
        except Exception as exc:
            logger.error("post-score share/value failed phone={}: {}", mask_phone(phone), exc)

    await _broadcast_recap(
        new_ctx,
        overall,
        signal_quality.quality_note,
        share_secret=(
            deps.settings.whatsapp_app_secret
            or deps.settings.webhook_verify_token
            or "pitwallai-season-share-local-secret"
        ),
    )

    _regenerate_results_page(race_key=race_key)

    logger.bind(race_key=race_key, overall=overall).info("Agent 5 scorer and learner complete")
    return new_ctx


def _regenerate_results_page(*, race_key: str) -> None:
    """Rebuild api/static/results.html after scoring (best-effort)."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "scripts" / "generate_results_page.py"
    try:
        subprocess.run(
            [sys.executable, str(script), "--season", "2026"],
            check=True,
            timeout=30,
            cwd=str(script.parent.parent),
        )
        logger.info("results_page_regenerated race_key={}", race_key)
    except Exception as exc:
        logger.warning("results_page_regen_failed race_key={} error={}", race_key, exc)


async def _broadcast_recap(
    ctx: RaceContext,
    season_accuracy: float,
    quality_note: str | None,
    *,
    share_secret: str,
) -> None:
    """Post-race recap with optional signal quality note for FULL cadence."""
    from intelligence.repository import get_fantasy_team
    from orchestrator.race_context import CadencePreference

    race_key = ctx.race_weekend.race_key
    season_finale = ctx.race_weekend.circuit_key == "yas_marina"
    subs = await list_subscribers_for_race_picks(race_key)
    next_weekend = get_next_race_weekend(after=ctx.race_weekend.race_utc)
    next_name = next_weekend.display_name if next_weekend else None
    days = (
        max(0, (next_weekend.race_utc - datetime.now(tz=UTC)).days)
        if next_weekend
        else None
    )

    for sub in subs:
        if sub.cadence_preference == CadencePreference.RACE_DAY_ONLY.value:
            continue
        picks = await get_picks_for_race(race_key, phone=sub.phone)
        if not picks:
            picks = await get_picks_for_race(race_key, phone=None)
        correct = sum(1 for p in picks if p.was_correct)
        total = len(picks) if picks else 3
        hit_pct = hit_rate_pct(picks) if picks else 0.0
        prev_hit_pct: float | None = None
        previous_race = prev_race_key(race_key)
        if previous_race:
            prev_picks = await get_picks_for_race(previous_race, phone=sub.phone)
            if not prev_picks:
                prev_picks = await get_picks_for_race(previous_race, phone=None)
            if prev_picks:
                prev_hit_pct = hit_rate_pct(prev_picks)

        swap_note: str | None = None
        team = await get_fantasy_team(sub.phone)
        pers = [p for p in picks if p.personalized and p.phone == sub.phone]
        if pers and correct > 0 and pers[0].actual_points_delta and pers[0].actual_points_delta > 0:
            swap_note = f"Best swap netted +{int(pers[0].actual_points_delta)} pts"
        elif pers and correct == 0 and pers[0].actual_points_delta and pers[0].actual_points_delta < 0:
            swap_note = (
                f"Suggested swap would have lost {int(abs(pers[0].actual_points_delta))} pts"
            )

        msg = format_recap_message(
            circuit_name=ctx.race_weekend.display_name,
            correct_count=correct,
            total_picks=total,
            season_accuracy_pct=season_accuracy,
            session_note=(
                (session_quality_note(picks) or "")
                + momentum_suffix(hit_pct, prev_hit_pct)
            ).strip(),
            swap_note=swap_note,
            next_race_name=next_name,
            days_until_next=days,
            nudge_team=team is None or team.remaining_budget is None,
        )
        if quality_note and sub.cadence_preference == CadencePreference.FULL.value:
            extra = f" {quality_note}"
            if len(msg) + len(extra) <= 300:
                msg = msg + extra

        try:
            await send_message(sub.phone, msg)
            if season_finale:
                season_recap = await build_season_recap(
                    phone=sub.phone,
                    season=2026,
                    share_base_url="https://pitwallai.app",
                    share_secret=share_secret,
                )
                season_msg = (
                    "🏁 Season complete.\n"
                    f"Your GP picks: {season_recap.personalized_accuracy_pct:.0f}% hit rate (race results)\n"
                    f"PitWallAI community: {season_recap.community_accuracy_pct:.0f}% GP hit rate\n"
                    f"Best call: {season_recap.best_call}\n"
                    f"Worst call: {season_recap.worst_call}\n"
                    f"Biggest signal this season: {season_recap.biggest_signal}\n"
                    f"See your full season: {season_recap.share_url}"
                )
                await send_message(sub.phone, season_msg)
        except Exception as exc:
            logger.error("Recap failed phone={}: {}", mask_phone(sub.phone), exc)
