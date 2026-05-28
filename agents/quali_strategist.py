"""Agent 3 — Quali Strategist (Saturday pre-lock picks)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from loguru import logger

from agents.base import AgentRunDependencies
from db.models import FantasyTeam
from fantasy.rules import (
    DRIVER_PRICES_M,
    driver_points_qualifying,
    driver_price_m,
    free_transfer_allowance,
    max_affordable_transfers,
    transfer_penalty_points,
)
from intelligence.pick_generator import (
    PickOutput,
    PickRecommendation,
    _aggregate_signals,
    build_qualifying_rows,
)
from intelligence.ownership import get_ownership_data
from intelligence.price_predictor import predict_price_changes
from intelligence.repository import (
    append_picks,
    get_fantasy_team,
    get_price_prediction_map,
    list_active_subscribers,
)
from intelligence.schemas import PracticeSignal, QualifyingRow
from openf1.client import OpenF1Client
from orchestrator.race_context import (
    ChampionshipRow,
    evolve_race_context,
    RaceContext,
)
from pitwallai.agents.radio_intercept.config import PitWallSettings
from whatsapp.message_format import format_generic_picks, format_personalized_picks
from whatsapp.sender import mask_phone, send_message

_ANOMALY_PENALTY = 15.0


@dataclass(frozen=True)
class _ScoredCombo:
    picks: list[PickRecommendation]
    expected_delta: float
    confidence: float
    reasoning: str
    personalized: bool
    raw_expected_delta: float | None = None


def _signal_weights(ctx: RaceContext) -> dict[str, float]:
    """Agent 5 quality multipliers (0.1–2.0)."""
    weights: dict[str, float] = {}
    if ctx.signal_quality is None:
        return weights
    for key, entry in ctx.signal_quality.entries.items():
        weights[key] = entry.weight_multiplier
    return weights


def _league_strategy(team: FantasyTeam) -> str:
    raw = (team.league_strategy or "").strip().upper()
    return raw if raw in {"SAFE", "ATTACK", "BALANCED"} else "BALANCED"


def _ownership_multiplier(tier: str, strategy: str, ownership_quality: float = 1.0) -> float:
    tier_u = tier.upper()
    if strategy == "ATTACK":
        base = {"HIGH": 0.7, "MEDIUM": 1.0, "LOW": 1.4, "UNKNOWN": 1.0}.get(tier_u, 1.0)
    elif strategy == "SAFE":
        base = {"HIGH": 1.2, "MEDIUM": 1.0, "LOW": 0.7, "UNKNOWN": 1.0}.get(tier_u, 1.0)
    else:
        base = {"HIGH": 0.9, "MEDIUM": 1.0, "LOW": 1.15, "UNKNOWN": 1.0}.get(tier_u, 1.0)
    return max(0.1, min(2.0, base * ownership_quality))


def _opponent_holds(team: FantasyTeam, driver_code: str) -> tuple[bool, str | None]:
    for raw in team.opponent_profiles or []:
        known = [str(x).upper() for x in (raw.get("known_drivers") or [])]
        if driver_code.upper() in known:
            return True, str(raw.get("nickname") or "").strip() or None
    return False, None


def _weight_for(weights: dict[str, float], signal_type: str) -> float:
    return max(0.1, min(2.0, weights.get(signal_type, 1.0)))


def _practice_modifier(sig: PracticeSignal | None, weights: dict[str, float]) -> float:
    if sig is None:
        return 0.0
    w = _weight_for(weights, "practice_sentiment")
    mod = sig.setup_sentiment * 8.0 * w + sig.tire_confidence * 4.0 * w
    mod -= len(sig.anomaly_flags) * _ANOMALY_PENALTY * 0.1 * _weight_for(weights, "anomaly_teammate_gap")
    return mod


def _qualifying_bonus(grid_pos: int | None, overtaking_difficulty: float) -> float:
    if grid_pos is None:
        return 0.0
    return max(0.0, (20 - grid_pos) * (1.0 - overtaking_difficulty) * 0.8)


def _conflict_note(
    code: str,
    practice: PracticeSignal | None,
    champ: ChampionshipRow | None,
) -> str:
    """Surface conflicting signals in reasoning — never hide."""
    parts: list[str] = []
    if practice and practice.setup_sentiment > 0.4:
        parts.append(f"{code} practice radio positive ({practice.setup_sentiment:+.2f})")
    if practice and practice.setup_sentiment < -0.2:
        parts.append(f"{code} practice concerns ({practice.setup_sentiment:+.2f})")
    if champ and champ.championship_pressure > 0.7:
        parts.append(f"{code} title pressure high ({champ.championship_pressure:.1f}) — higher variance")
    elif champ and champ.championship_pressure < 0.2:
        parts.append(f"{code} low championship pressure — conservative race likely")
    if practice and len(practice.anomaly_flags) >= 2:
        parts.append(f"Conflict: {len(practice.anomaly_flags)} practice anomaly flags")
    return "; ".join(parts) if parts else ""


def _score_driver(
    code: str,
    ctx: RaceContext,
    grid: dict[str, int],
    signals: dict[str, PracticeSignal],
    weights: dict[str, float],
) -> tuple[float, str]:
    circuit = ctx.circuit_profile
    champ = (ctx.championship_snapshot or {}).get(code)
    sig = signals.get(code)
    base = 40.0
    intel = ctx.circuit_intel or {}
    hist = intel.get("avg_positions_gained_top5", circuit.positions_gained_ceiling)
    base += min(float(hist), circuit.positions_gained_ceiling) * 1.5
    grid_pos = grid.get(code)
    if grid_pos is not None:
        base += float(driver_points_qualifying(grid_pos))
    base += _qualifying_bonus(grid_pos, circuit.overtaking_difficulty)
    base += _practice_modifier(sig, weights)
    if champ:
        base += champ.championship_pressure * 3.0
    base = min(base, circuit.positions_gained_ceiling * 4.0)
    reasoning = _conflict_note(code, sig, champ)
    return base, reasoning


async def _load_qualifying(client: OpenF1Client, ctx: RaceContext) -> list[QualifyingRow]:
    if ctx.qualifying_result:
        return ctx.qualifying_result
    sk = await client.find_session_key(
        year=2026,
        circuit_short_name=ctx.circuit_profile.openf1_circuit_name,
        session_name="Qualifying",
    )
    if sk is None:
        return []
    return await build_qualifying_rows(client, sk)


def _enumerate_single_transfers(
    team: FantasyTeam,
    ctx: RaceContext,
    grid: dict[str, int],
    signals: dict[str, PracticeSignal],
    weights: dict[str, float],
) -> list[_ScoredCombo]:
    roster = [c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c]
    budget = team.remaining_budget or 0.0
    limitless = bool((team.chips_used or {}).get("limitless"))
    free_allowance = free_transfer_allowance(
        team.transfers_available,
        limitless_chip=limitless,
    )
    pool = set(DRIVER_PRICES_M) - set(roster)
    combos: list[_ScoredCombo] = []

    for out_code in roster:
        out_price = driver_price_m(out_code)
        for in_code in pool:
            in_price = driver_price_m(in_code)
            if in_price - out_price > budget:
                continue
            in_score, in_reason = _score_driver(in_code, ctx, grid, signals, weights)
            out_score, out_reason = _score_driver(out_code, ctx, grid, signals, weights)
            out_pos, in_pos = grid.get(out_code), grid.get(in_code)
            if out_pos is not None and in_pos is not None:
                delta = float(
                    driver_points_qualifying(in_pos)
                    - driver_points_qualifying(out_pos)
                    + transfer_penalty_points(1, free_allowance)
                )
            else:
                delta = round(in_score - out_score, 1)
            conf = min(95.0, max(35.0, 55.0 + delta))
            sig = signals.get(in_code)
            if sig and len(sig.anomaly_flags) >= 2:
                conf -= _ANOMALY_PENALTY
            reasoning = f"{in_reason}. vs keeping {out_code}: {out_reason}."
            pick = PickRecommendation(
                rank=1,
                headline=f"Swap {out_code} → {in_code}. +{delta:.0f} expected pts.",
                confidence=round(conf, 1),
                reasoning=reasoning[:500],
                driver_code=in_code,
                predicted_points_delta=delta,
                transfer_out=out_code,
                transfer_in=in_code,
            )
            combos.append(
                _ScoredCombo([pick], delta, conf, reasoning, True, raw_expected_delta=delta),
            )
    return combos


def _enumerate_double_transfers(
    team: FantasyTeam,
    ctx: RaceContext,
    grid: dict[str, int],
    signals: dict[str, PracticeSignal],
    weights: dict[str, float],
) -> list[_ScoredCombo]:
    limitless = bool((team.chips_used or {}).get("limitless"))
    transfer_cap = max_affordable_transfers(
        team.transfers_available,
        limitless_chip=limitless,
    )
    free_allowance = free_transfer_allowance(
        team.transfers_available,
        limitless_chip=limitless,
    )
    if transfer_cap < 2:
        return []
    roster = [c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c]
    budget = team.remaining_budget or 0.0
    pool = list(set(DRIVER_PRICES_M) - set(roster))
    combos: list[_ScoredCombo] = []

    for out_pair in combinations(roster, 2):
        for in_pair in combinations(pool, 2):
            cost = sum(driver_price_m(c) for c in in_pair) - sum(driver_price_m(c) for c in out_pair)
            if cost > budget:
                continue
            delta = 0.0
            reasons: list[str] = []
            picks: list[PickRecommendation] = []
            for out_c, in_c in zip(out_pair, in_pair, strict=True):
                in_s, r_in = _score_driver(in_c, ctx, grid, signals, weights)
                out_s, r_out = _score_driver(out_c, ctx, grid, signals, weights)
                out_pos, in_pos = grid.get(out_c), grid.get(in_c)
                if out_pos is not None and in_pos is not None:
                    delta += driver_points_qualifying(in_pos) - driver_points_qualifying(out_pos)
                else:
                    delta += in_s - out_s
                reasons.append(f"{out_c}→{in_c}: {r_in}")
            delta = round(
                float(delta) + transfer_penalty_points(2, free_allowance),
                1,
            )
            conf = min(90.0, max(40.0, 50.0 + delta))
            reasoning = " | ".join(reasons)
            picks.append(
                PickRecommendation(
                    rank=1,
                    headline=f"Double swap {out_pair[0]},{out_pair[1]} → {in_pair[0]},{in_pair[1]}",
                    confidence=conf,
                    reasoning=reasoning[:500],
                    driver_code=in_pair[0],
                    predicted_points_delta=delta,
                    transfer_out=out_pair[0],
                    transfer_in=in_pair[0],
                )
            )
            combos.append(_ScoredCombo(picks, delta, conf, reasoning, True))
    return combos


async def generate_quali_picks(
    ctx: RaceContext,
    *,
    user_team: FantasyTeam | None,
    generated_by: str,
) -> PickOutput:
    """Generate top-3 picks from full RaceContext."""
    flat_signals: list[PracticeSignal] = []
    if ctx.practice_signals:
        for session_sigs in ctx.practice_signals.values():
            flat_signals.extend(session_sigs)
    signal_map = _aggregate_signals(flat_signals)
    price_predictions = await get_price_prediction_map(ctx.race_weekend.race_key)
    grid = {q.driver_code: q.grid_position for q in (ctx.qualifying_result or [])}
    weights = _signal_weights(ctx)
    circuit = ctx.circuit_profile

    if user_team and user_team.remaining_budget is not None:
        combos = _enumerate_single_transfers(user_team, ctx, grid, signal_map, weights)
        combos.extend(_enumerate_double_transfers(user_team, ctx, grid, signal_map, weights))
        raw_ranked = sorted(combos, key=lambda c: (c.expected_delta, c.confidence), reverse=True)
        top = raw_ranked[:3]
        league_mode = bool(user_team.league_mode_enabled)
        strategy = _league_strategy(user_team)
        if league_mode and top:
            ownership = await get_ownership_data(ctx.race_weekend.race_key)
            if not any((v.combined_ownership_pct is not None) for v in ownership.values()):
                ownership = {}
            ownership_quality = 1.0
            if ctx.signal_quality and "contrarian_low_ownership" in ctx.signal_quality.entries:
                ownership_quality = ctx.signal_quality.entries["contrarian_low_ownership"].weight_multiplier

            adjusted: list[_ScoredCombo] = []
            for combo in combos:
                p0 = combo.picks[0]
                own = ownership.get(p0.transfer_in or p0.driver_code)
                tier = own.ownership_tier if own else "UNKNOWN"
                mult = _ownership_multiplier(tier, strategy, ownership_quality=ownership_quality)
                opp_conflict, opp_nick = _opponent_holds(user_team, p0.transfer_in or p0.driver_code)
                if opp_conflict:
                    mult *= 0.8 if strategy == "ATTACK" else (1.1 if strategy == "SAFE" else 1.0)
                new_delta = round(combo.expected_delta * mult, 1)
                conflict_note = ""
                raw_best = raw_ranked[0].picks[0] if raw_ranked else None
                if raw_best and raw_best.transfer_in != (p0.transfer_in or p0.driver_code):
                    conflict_note = (
                        f" Highest raw expected pts: {raw_best.transfer_in or raw_best.driver_code}. "
                        f"Best league play: {p0.transfer_in or p0.driver_code} "
                        f"(low ownership, {strategy} mode). You decide."
                    )
                reason = combo.reasoning
                if opp_conflict:
                    reason += f" {opp_nick or 'Opponent'} likely holds {p0.transfer_in or p0.driver_code}."
                reason += conflict_note
                pick = p0.model_copy(
                    update={
                        "predicted_points_delta": new_delta,
                        "ownership_tier": tier,
                        "league_strategy_applied": strategy,
                        "opponent_conflict": opp_conflict,
                        "is_contrarian": bool(tier == "LOW" and p0.confidence > 60),
                        "reasoning": reason[:500],
                    }
                )
                adjusted.append(
                    _ScoredCombo(
                        picks=[pick],
                        expected_delta=new_delta,
                        confidence=combo.confidence,
                        reasoning=reason,
                        personalized=True,
                        raw_expected_delta=combo.expected_delta,
                    )
                )
            if adjusted and any((c.picks[0].ownership_tier != "UNKNOWN") for c in adjusted):
                adjusted.sort(key=lambda c: (c.expected_delta, c.confidence), reverse=True)
                top = adjusted[:3]

        picks: list[PickRecommendation] = []
        for rank, combo in enumerate(top, start=1):
            p = combo.picks[0]
            picks.append(
                p.model_copy(update={"rank": rank, "reasoning": combo.reasoning[:500]}),
            )
        if picks:
            has_practice = bool(flat_signals)
            patched: list[PickRecommendation] = []
            for p in picks:
                pred_in = price_predictions.get(p.transfer_in or p.driver_code)
                pred_out = price_predictions.get(p.transfer_out or "")
                note_parts: list[str] = []
                if (
                    has_practice
                    and pred_in
                    and pred_in.predicted_direction == "UP"
                    and pred_in.confidence > 0.6
                ):
                    note_parts.append(f"{p.transfer_in or p.driver_code} rising")
                if (
                    has_practice
                    and pred_out
                    and pred_out.predicted_direction == "DOWN"
                    and pred_out.confidence > 0.6
                    and p.transfer_out
                ):
                    note_parts.append(f"{p.transfer_out} falling")
                patched.append(
                    p.model_copy(
                        update={
                            "price_direction": (pred_in.predicted_direction if pred_in else None),
                            "price_magnitude": (float(pred_in.predicted_magnitude) if pred_in else None),
                            "price_confidence": (float(pred_in.confidence) if pred_in else None),
                            "price_timing_note": (" · ".join(note_parts)[:60] if note_parts else None),
                        }
                    )
                )
            return PickOutput(
                picks=patched,
                personalized=True,
                circuit_note=f"{circuit.display_name}: lock approaching.",
                confidence_note="Signals merged from practice, quali, and championship context.",
                generated_by=generated_by,
            )

    scored: list[tuple[str, float, str]] = []
    for code in DRIVER_PRICES_M:
        score, reason = _score_driver(code, ctx, grid, signal_map, weights)
        scored.append((code, score, reason))
    scored.sort(key=lambda x: x[1], reverse=True)
    picks = []
    for rank, (code, score, reason) in enumerate(scored[:3], start=1):
        conf = min(90.0, max(40.0, score * 0.9))
        sig = signal_map.get(code)
        if sig and len(sig.anomaly_flags) >= 2:
            conf -= _ANOMALY_PENALTY
        picks.append(
            PickRecommendation(
                rank=rank,
                headline=f"Target {code} — composite {score:.0f}",
                confidence=round(conf, 1),
                reasoning=reason[:500],
                driver_code=code,
                price_direction=(price_predictions.get(code).predicted_direction if code in price_predictions else None),
                price_magnitude=(
                    float(price_predictions[code].predicted_magnitude) if code in price_predictions else None
                ),
                price_confidence=(float(price_predictions[code].confidence) if code in price_predictions else None),
                price_timing_note=(
                    f"{code} rising"
                    if (
                        flat_signals
                        and code in price_predictions
                        and price_predictions[code].predicted_direction == "UP"
                        and price_predictions[code].confidence > 0.6
                    )
                    else None
                ),
            )
        )
    return PickOutput(
        picks=picks,
        personalized=False,
        circuit_note=f"{circuit.display_name} quali picks.",
        confidence_note="Text TEAM for budget-aware personalised swaps.",
        generated_by=generated_by,
    )


async def run_quali_strategist(
    ctx: RaceContext,
    deps: AgentRunDependencies,
) -> RaceContext:
    """Run Agent 3 and broadcast quali picks to eligible subscribers."""
    client = deps.openf1_client
    qualifying = await _load_qualifying(client, ctx)
    new_ctx = evolve_race_context(ctx, qualifying_result=qualifying)

    settings: PitWallSettings = deps.settings
    generated_by = (
        "rules"
        if settings.decode_backend.value == "rules"
        else f"{settings.llm_provider}:{settings.llm_model}"
    )

    subs = await list_active_subscribers()
    race_key = new_ctx.race_weekend.race_key
    await predict_price_changes(race_key, new_ctx.circuit_profile.openf1_circuit_name)

    for sub in subs:
        cadence = sub.cadence_preference
        if cadence not in ("FULL", "RACE_DAY_ONLY"):
            continue
        try:
            team = await get_fantasy_team(sub.phone)
            output = await generate_quali_picks(new_ctx, user_team=team, generated_by=generated_by)
            await append_picks(
                race_key,
                output,
                phone=sub.phone,
                circuit_key=new_ctx.race_weekend.circuit_key,
            )
            if team and team.remaining_budget is not None:
                msg = format_personalized_picks(
                    new_ctx.race_weekend, output, timezone=sub.timezone
                )
            else:
                msg = format_generic_picks(new_ctx.race_weekend, output, timezone=sub.timezone)
            await send_message(sub.phone, msg)
        except Exception as exc:
            logger.error("Quali pick send failed phone={}: {}", mask_phone(sub.phone), exc)

    logger.bind(race_key=race_key, subscribers=len(subs)).info("Agent 3 quali strategist complete")
    return new_ctx
