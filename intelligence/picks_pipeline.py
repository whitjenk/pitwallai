"""End-to-end practice analysis and pick generation for a race weekend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from circuits.profiles import CircuitProfile
from intelligence.active_weekend import ActiveWeekend, resolve_active_weekend
from intelligence.context import OrchestratorContext, get_orchestrator_context
from intelligence.pick_generator import (
    build_qualifying_rows,
    build_weather_forecast,
    generate_and_log_picks,
    generate_picks,
)
from intelligence.price_predictor import predict_price_changes
from intelligence.repository import get_price_prediction_map
from intelligence.practice_analyst import analyze_practice_weekend
from intelligence.repository import get_fantasy_team
from intelligence.schemas import PickGeneratorInput, PickOutput
from openf1.client import OpenF1Client
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore


@dataclass(frozen=True, slots=True)
class PicksRunResult:
    """Result of a full picks pipeline run."""

    output: PickOutput
    weekend: ActiveWeekend
    circuit: CircuitProfile
    generated_at: datetime
    practice_signal_count: int


def _generated_by_label(settings: PitWallSettings) -> str:
    if settings.decode_backend.value == "rules":
        return "rules"
    return f"{settings.llm_provider}:{settings.llm_model}"


async def run_picks_pipeline(
    *,
    client: OpenF1Client,
    agent: RadioInterceptAgent,
    vector_store: MockVectorStore,
    settings: PitWallSettings,
    ctx: OrchestratorContext | None = None,
    year: int | None = None,
    circuit_key: str | None = None,
    phone: str | None = None,
    persist_practice: bool = True,
    persist_picks: bool = True,
    weekend: ActiveWeekend | None = None,
) -> PicksRunResult:
    """
    Run practice analysis then generate (and optionally log) picks.

    Args:
        client: OpenF1 REST client.
        agent: Radio intercept agent for practice radio decode.
        vector_store: Seeded vector store for decode context.
        settings: PitWall settings (provider label for output).
        ctx: Orchestrator context; loaded from startup if omitted.
        year: Championship year override.
        circuit_key: Circuit key override (PITWALL_CIRCUIT_KEY).
        phone: Subscriber phone for personalized PATH A picks.
        persist_practice: Write practice_signals to Postgres.
        persist_picks: Append rows to picks audit log.
        weekend: Pre-resolved weekend; resolved via OpenF1 if omitted.

    Returns:
        PicksRunResult with sacred PickOutput schema.
    """
    orchestrator = ctx or get_orchestrator_context()
    race_year = year or datetime.now(tz=UTC).year

    active = weekend or await resolve_active_weekend(
        client,
        orchestrator,
        year=race_year,
        circuit_key_override=circuit_key,
    )

    circuit = orchestrator.get_circuit(active.circuit_key)
    if circuit is None:
        raise ValueError(f"Circuit profile missing for {active.circuit_key}")

    practice_signals = await analyze_practice_weekend(
        client=client,
        agent=agent,
        vector_store=vector_store,
        circuit=circuit,
        year=active.year,
        persist=persist_practice,
    )

    qualifying: list = []
    if active.qualifying_session_key is not None:
        qualifying = await build_qualifying_rows(client, active.qualifying_session_key)

    weather_session = active.qualifying_session_key or active.race_session_key
    weather_forecast = None
    if weather_session is not None:
        samples = await client.get_weather(weather_session)
        if samples:
            weather_forecast = build_weather_forecast(weather_session, samples)

    user_team = await get_fantasy_team(phone) if phone else None
    await predict_price_changes(active.race_key, circuit.openf1_circuit_name)
    price_predictions = await get_price_prediction_map(active.race_key)

    generator_input = PickGeneratorInput(
        circuit=circuit,
        practice_signals=practice_signals,
        qualifying_result=qualifying,
        weather_forecast=weather_forecast,
        user_team=user_team,
        price_predictions=price_predictions,
        race_key=active.race_key,
        generated_by=_generated_by_label(settings),
    )

    if persist_picks:
        output = await generate_and_log_picks(generator_input, phone=phone)
    else:
        output = generate_picks(generator_input)

    return PicksRunResult(
        output=output,
        weekend=active,
        circuit=circuit,
        generated_at=datetime.now(tz=UTC),
        practice_signal_count=len(practice_signals),
    )
