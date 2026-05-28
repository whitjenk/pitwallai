"""Agent 3 — Quali Strategist (Saturday pre-lock picks)."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from loguru import logger

from agents.base import AgentRunDependencies
from db.models import FantasyTeam
from intelligence.pick_generator import (
    PickOutput,
    PickRecommendation,
    _DRIVER_PRICE_M,
    _aggregate_signals,
    build_qualifying_rows,
)
from intelligence.repository import append_picks, get_fantasy_team, list_active_subscribers
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


def _signal_weights(ctx: RaceContext) -> dict[str, float]:
    """Agent 5 quality multipliers (0.1–2.0)."""
    weights: dict[str, float] = {}
    if ctx.signal_quality is None:
        return weights
    for key, entry in ctx.signal_quality.entries.items():
        weights[key] = entry.weight_multiplier
    return weights


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
    base += _qualifying_bonus(grid.get(code), circuit.overtaking_difficulty)
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
    pool = set(_DRIVER_PRICE_M) - set(roster)
    combos: list[_ScoredCombo] = []

    for out_code in roster:
        out_price = _DRIVER_PRICE_M.get(out_code, 15.0)
        for in_code in pool:
            in_price = _DRIVER_PRICE_M.get(in_code, 15.0)
            if in_price - out_price > budget:
                continue
            in_score, in_reason = _score_driver(in_code, ctx, grid, signals, weights)
            out_score, out_reason = _score_driver(out_code, ctx, grid, signals, weights)
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
                _ScoredCombo([pick], delta, conf, reasoning, True),
            )
    return combos


def _enumerate_double_transfers(
    team: FantasyTeam,
    ctx: RaceContext,
    grid: dict[str, int],
    signals: dict[str, PracticeSignal],
    weights: dict[str, float],
) -> list[_ScoredCombo]:
    if team.transfers_available < 2:
        return []
    roster = [c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c]
    budget = team.remaining_budget or 0.0
    pool = list(set(_DRIVER_PRICE_M) - set(roster))
    combos: list[_ScoredCombo] = []

    for out_pair in combinations(roster, 2):
        for in_pair in combinations(pool, 2):
            cost = sum(_DRIVER_PRICE_M.get(c, 15.0) for c in in_pair) - sum(
                _DRIVER_PRICE_M.get(c, 15.0) for c in out_pair
            )
            if cost > budget:
                continue
            delta = 0.0
            reasons: list[str] = []
            picks: list[PickRecommendation] = []
            for out_c, in_c in zip(out_pair, in_pair, strict=True):
                in_s, r_in = _score_driver(in_c, ctx, grid, signals, weights)
                out_s, r_out = _score_driver(out_c, ctx, grid, signals, weights)
                delta += in_s - out_s
                reasons.append(f"{out_c}→{in_c}: {r_in}")
            delta = round(delta, 1)
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


def generate_quali_picks(
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
    grid = {q.driver_code: q.grid_position for q in (ctx.qualifying_result or [])}
    weights = _signal_weights(ctx)
    circuit = ctx.circuit_profile

    if user_team and user_team.remaining_budget is not None:
        combos = _enumerate_single_transfers(user_team, ctx, grid, signal_map, weights)
        combos.extend(_enumerate_double_transfers(user_team, ctx, grid, signal_map, weights))
        combos.sort(key=lambda c: (c.expected_delta, c.confidence), reverse=True)
        top = combos[:3]
        picks: list[PickRecommendation] = []
        for rank, combo in enumerate(top, start=1):
            p = combo.picks[0]
            picks.append(
                p.model_copy(update={"rank": rank, "reasoning": combo.reasoning[:500]}),
            )
        if picks:
            return PickOutput(
                picks=picks,
                personalized=True,
                circuit_note=f"{circuit.display_name}: lock approaching.",
                confidence_note="Signals merged from practice, quali, and championship context.",
                generated_by=generated_by,
            )

    scored: list[tuple[str, float, str]] = []
    for code in _DRIVER_PRICE_M:
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

    for sub in subs:
        cadence = sub.cadence_preference
        if cadence not in ("FULL", "RACE_DAY_ONLY"):
            continue
        try:
            team = await get_fantasy_team(sub.phone)
            output = generate_quali_picks(new_ctx, user_team=team, generated_by=generated_by)
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
