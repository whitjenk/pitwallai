"""Personalized and generic fantasy pick generation."""

from __future__ import annotations

from dataclasses import dataclass

from circuits.profiles import CircuitProfile
from db.models import FantasyTeam
from intelligence.drivers import driver_code_for
from intelligence.repository import append_picks
from intelligence.schemas import (
    PickGeneratorInput,
    PickOutput,
    PickRecommendation,
    PracticeSignal,
    QualifyingRow,
    WeatherForecast,
)
from openf1.client import OpenF1Client

# Approximate F1 Fantasy prices (USD millions) — update per season.
_DRIVER_PRICE_M: dict[str, float] = {
    "VER": 30.0,
    "NOR": 28.5,
    "LEC": 27.0,
    "PIA": 26.0,
    "SAI": 24.0,
    "HAM": 23.0,
    "RUS": 22.0,
    "PER": 20.0,
    "ALO": 18.0,
    "ALB": 16.0,
    "GAS": 14.0,
    "OCO": 13.0,
    "STR": 12.0,
    "TSU": 11.0,
    "HUL": 10.0,
    "MAG": 9.5,
    "BOT": 9.0,
    "ZHOU": 8.5,
}

_ANOMALY_CONFIDENCE_PENALTY = 12.0


def signal_weight_multiplier(
    signal_type: str,
    *,
    circuit_key: str | None = None,
    quality_entries: dict[str, float] | None = None,
) -> float:
    """
    Agent 5 learned weight for a signal type (0.1–2.0).

    Args:
        signal_type: e.g. practice_sentiment, anomaly_teammate_gap.
        circuit_key: Reserved for per-circuit lookup via DB at call site.
        quality_entries: Pre-loaded multipliers from SignalQuality.

    Returns:
        Weight multiplier capped to [0.1, 2.0].
    """
    _ = circuit_key
    if not quality_entries:
        return 1.0
    raw = quality_entries.get(signal_type, 1.0)
    return max(0.1, min(2.0, raw))


@dataclass(frozen=True)
class _TransferOption:
    out_code: str
    in_code: str
    budget_saved: float
    expected_delta: float
    confidence: float
    reasoning: str


def _driver_score(
    code: str,
    *,
    circuit: CircuitProfile,
    signals: dict[str, PracticeSignal],
    grid: dict[str, int],
    signal_weights: dict[str, float] | None = None,
) -> float:
    """Score a driver for generic or transfer-in evaluation."""
    weights = signal_weights or {}
    w_practice = signal_weight_multiplier("practice_sentiment", quality_entries=weights)
    w_anomaly = signal_weight_multiplier("anomaly_teammate_gap", quality_entries=weights)
    sig = signals.get(code)
    base = 50.0
    if sig:
        base += sig.setup_sentiment * 15.0 * w_practice
        base += sig.tire_confidence * 10.0 * w_practice
        base += sig.pace_satisfaction * 10.0 * w_practice
        if len(sig.anomaly_flags) >= 2:
            base -= _ANOMALY_CONFIDENCE_PENALTY * (len(sig.anomaly_flags) - 1) * w_anomaly
    grid_pos = grid.get(code)
    if grid_pos is not None:
        ceiling = circuit.positions_gained_ceiling
        base += max(0, ceiling - grid_pos) * 2.5
    base += (1.0 - circuit.overtaking_difficulty) * 8.0
    return base


def _aggregate_signals(signals: list[PracticeSignal]) -> dict[str, PracticeSignal]:
    """Merge FP1/FP2 signals per driver (prefer FP2, merge flags)."""
    merged: dict[str, PracticeSignal] = {}
    for sig in sorted(signals, key=lambda s: s.session):
        existing = merged.get(sig.driver_code)
        if existing is None:
            merged[sig.driver_code] = sig
            continue
        merged[sig.driver_code] = sig.model_copy(
            update={
                "anomaly_flags": sorted(set(existing.anomaly_flags + sig.anomaly_flags)),
                "raw_evidence": (existing.raw_evidence + sig.raw_evidence)[:10],
            }
        )
    return merged


def _confidence_note(signals: list[PracticeSignal], weather: WeatherForecast | None) -> str:
    """One sentence on signal quality."""
    if not signals:
        return "Limited practice radio available — lean on qualifying and circuit history."
    anomaly_drivers = sum(1 for s in signals if len(s.anomaly_flags) >= 2)
    if weather and weather.rainfall_likely:
        return (
            f"Rain likely — circuit weather sensitivity matters; "
            f"{anomaly_drivers} drivers flagged with practice anomalies."
        )
    return (
        f"Practice radio processed for {len({s.driver_code for s in signals})} drivers; "
        f"{anomaly_drivers} with multiple anomaly flags."
    )


def _circuit_note(circuit: CircuitProfile) -> str:
    """One sentence on circuit fantasy traits."""
    return (
        f"{circuit.display_name}: overtaking difficulty {circuit.overtaking_difficulty:.0%}, "
        f"positions-gained ceiling ~{circuit.positions_gained_ceiling}. {circuit.notes}"
    )[:240]


def _enumerate_transfers(
    team: FantasyTeam,
    *,
    circuit: CircuitProfile,
    signals: dict[str, PracticeSignal],
    grid: dict[str, int],
) -> list[_TransferOption]:
    """Enumerate legal single-driver swaps within budget and transfer count."""
    roster = [
        c
        for c in (
            team.driver_1,
            team.driver_2,
            team.driver_3,
            team.driver_4,
            team.driver_5,
        )
        if c
    ]
    if not roster or team.remaining_budget is None:
        return []

    budget = team.remaining_budget
    transfers = team.transfers_available
    if transfers <= 0:
        return []

    options: list[_TransferOption] = []
    pool = set(_DRIVER_PRICE_M.keys()) - set(roster)

    for out_code in roster:
        out_price = _DRIVER_PRICE_M.get(out_code, 15.0)
        for in_code in pool:
            in_price = _DRIVER_PRICE_M.get(in_code, 15.0)
            delta_cost = in_price - out_price
            if delta_cost > budget:
                continue
            out_score = _driver_score(out_code, circuit=circuit, signals=signals, grid=grid)
            in_score = _driver_score(in_code, circuit=circuit, signals=signals, grid=grid)
            expected = round((in_score - out_score) * 0.15, 1)
            in_sig = signals.get(in_code)
            out_sig = signals.get(out_code)
            conf = min(95.0, max(35.0, 55.0 + expected * 2.0))
            if in_sig and len(in_sig.anomaly_flags) >= 2:
                conf -= _ANOMALY_CONFIDENCE_PENALTY
            if out_sig and len(out_sig.anomaly_flags) >= 2:
                conf += 5.0
            reasoning_parts = [
                f"{in_code} grid P{grid.get(in_code, '?')}",
                "clean practice" if in_sig and len(in_sig.anomaly_flags) < 2 else "practice flags",
            ]
            if out_sig and len(out_sig.anomaly_flags) >= 2:
                reasoning_parts.append(
                    f"{out_code} had {len(out_sig.anomaly_flags)} anomaly flags in FP2"
                )
            options.append(
                _TransferOption(
                    out_code=out_code,
                    in_code=in_code,
                    budget_saved=round(out_price - in_price, 1),
                    expected_delta=expected,
                    confidence=round(conf, 1),
                    reasoning="; ".join(reasoning_parts),
                )
            )

    options.sort(key=lambda o: (o.expected_delta, o.confidence), reverse=True)
    return options[:20]


async def _historical_points_hint(
    client: OpenF1Client,
    *,
    circuit: CircuitProfile,
    year: int,
    driver_code: str,
) -> float:
    """Rough prior from last year's race classification at this circuit."""
    sk = await client.find_session_key(
        year=year - 1,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Race",
    )
    if sk is None:
        return 0.0
    results = await client.get_session_results(sk)
    for row in results:
        if driver_code_for(row.driver_number) == driver_code and row.position is not None:
            return max(0.0, 26.0 - float(row.position) * 1.2)
    return 0.0


def generate_picks(ctx: PickGeneratorInput) -> PickOutput:
    """
    Generate top-3 picks (PATH A personalized or PATH B generic).

    CircuitProfile must be supplied via context — never fetched here.
    """
    signal_map = _aggregate_signals(ctx.practice_signals)
    grid = {q.driver_code: q.grid_position for q in ctx.qualifying_result}

    if ctx.user_team and _team_is_actionable(ctx.user_team):
        return _path_personalized(ctx, signal_map, grid)
    return _path_generic(ctx, signal_map, grid)


def _team_is_actionable(team: FantasyTeam) -> bool:
    """True when enough profile fields exist for transfer enumeration."""
    drivers = [team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5]
    return any(drivers) and team.remaining_budget is not None


def _path_personalized(
    ctx: PickGeneratorInput,
    signals: dict[str, PracticeSignal],
    grid: dict[str, int],
) -> PickOutput:
    assert ctx.user_team is not None
    options = _enumerate_transfers(
        ctx.user_team,
        circuit=ctx.circuit,
        signals=signals,
        grid=grid,
    )
    picks: list[PickRecommendation] = []
    for rank, opt in enumerate(options[:3], start=1):
        saved = opt.budget_saved
        save_str = f"Saves ${abs(saved):.1f}M." if saved >= 0 else f"Costs ${abs(saved):.1f}M."
        headline = (
            f"Swap {opt.out_code} → {opt.in_code}. {save_str} "
            f"+{opt.expected_delta:.0f} expected pts."
        )
        picks.append(
            PickRecommendation(
                rank=rank,
                headline=headline[:200],
                confidence=opt.confidence,
                reasoning=(
                    f"Confidence {opt.confidence:.0f}%. {opt.reasoning}. "
                    f"{opt.in_code} suits {ctx.circuit.circuit_key} profile."
                ),
                driver_code=opt.in_code,
                predicted_points_delta=opt.expected_delta,
                transfer_out=opt.out_code,
                transfer_in=opt.in_code,
            )
        )
    if not picks:
        return _path_generic(ctx, signals, grid)

    return PickOutput(
        picks=picks,
        personalized=True,
        circuit_note=_circuit_note(ctx.circuit),
        confidence_note=_confidence_note(ctx.practice_signals, ctx.weather_forecast),
        generated_by=ctx.generated_by,
    )


def _path_generic(
    ctx: PickGeneratorInput,
    signals: dict[str, PracticeSignal],
    grid: dict[str, int],
) -> PickOutput:
    scored: list[tuple[str, float]] = []
    for code in _DRIVER_PRICE_M:
        scored.append(
            (
                code,
                _driver_score(code, circuit=ctx.circuit, signals=signals, grid=grid),
            )
        )
    scored.sort(key=lambda x: x[1], reverse=True)
    picks: list[PickRecommendation] = []
    for rank, (code, score) in enumerate(scored[:3], start=1):
        sig = signals.get(code)
        conf = min(90.0, max(40.0, score * 0.9))
        if sig and len(sig.anomaly_flags) >= 2:
            conf -= _ANOMALY_CONFIDENCE_PENALTY
        reasoning = f"Grid P{grid.get(code, '?')}; practice score {score:.0f}"
        if sig and sig.anomaly_flags:
            reasoning += f"; flags: {', '.join(sig.anomaly_flags[:3])}"
        picks.append(
            PickRecommendation(
                rank=rank,
                headline=f"Target {code} — strong weekend signals ({score:.0f} composite).",
                confidence=round(conf, 1),
                reasoning=reasoning,
                driver_code=code,
                predicted_points_delta=None,
            )
        )
    note = _confidence_note(ctx.practice_signals, ctx.weather_forecast)
    if not ctx.user_team:
        note += " Set up your team for budget-aware picks → text TEAM"

    return PickOutput(
        picks=picks,
        personalized=False,
        circuit_note=_circuit_note(ctx.circuit),
        confidence_note=note[:240],
        generated_by=ctx.generated_by,
    )


async def generate_and_log_picks(
    ctx: PickGeneratorInput,
    *,
    phone: str | None = None,
) -> PickOutput:
    """
    Generate picks and append to the audit log.

    Args:
        ctx: Generator input with injected circuit profile.
        phone: Subscriber phone for personalized picks.

    Returns:
        PickOutput sacred schema.
    """
    output = generate_picks(ctx)
    await append_picks(ctx.race_key, output, phone=phone, circuit_key=ctx.circuit.circuit_key)
    return output


def build_weather_forecast(session_key: int, samples: list) -> WeatherForecast:
    """Build WeatherForecast from OpenF1 weather samples."""
    rainfall = any(bool(s.rainfall) for s in samples if getattr(s, "rainfall", None) is not None)
    air = next((s.air_temperature for s in reversed(samples) if getattr(s, "air_temperature", None)), None)
    track = next(
        (s.track_temperature for s in reversed(samples) if getattr(s, "track_temperature", None)),
        None,
    )
    summary = "Rain likely" if rainfall else "Dry conditions expected"
    return WeatherForecast(
        session_key=session_key,
        rainfall_likely=bool(rainfall),
        air_temperature_c=air,
        track_temperature_c=track,
        summary=summary,
    )


async def build_qualifying_rows(client: OpenF1Client, session_key: int) -> list[QualifyingRow]:
    """Map session results to QualifyingRow list."""
    results = await client.get_session_results(session_key)
    rows: list[QualifyingRow] = []
    for row in results:
        if row.position is None:
            continue
        rows.append(
            QualifyingRow(
                driver_number=row.driver_number,
                driver_code=driver_code_for(row.driver_number),
                grid_position=row.position,
                session_key=session_key,
            )
        )
    rows.sort(key=lambda r: r.grid_position)
    return rows
