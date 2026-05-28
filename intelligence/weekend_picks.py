"""Pick generation bound to the hard-coded race calendar."""

from __future__ import annotations

from datetime import UTC, datetime

from circuits.profiles import CircuitProfile, get_circuit_profile
from intelligence.active_weekend import ActiveWeekend
from intelligence.context import OrchestratorContext, get_orchestrator_context
from intelligence.pick_generator import (
    build_qualifying_rows,
    build_weather_forecast,
    generate_picks,
)
from intelligence.price_predictor import predict_price_changes
from intelligence.repository import get_price_prediction_map
from intelligence.practice_analyst import analyze_practice_weekend
from intelligence.repository import append_picks, get_fantasy_team, load_practice_signals
from intelligence.schemas import PickGeneratorInput, PickOutput
from openf1.client import OpenF1Client
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore
from scheduler.calendar import RaceWeekend, profile_circuit_key


def _generated_by_label(settings: PitWallSettings) -> str:
    if settings.decode_backend.value == "rules":
        return "rules"
    return f"{settings.llm_provider}:{settings.llm_model}"


async def _resolve_openf1_weekend(
    client: OpenF1Client,
    weekend: RaceWeekend,
    circuit: CircuitProfile,
) -> ActiveWeekend:
    """Attach OpenF1 session keys to a calendar weekend."""
    race_sk = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Race",
    )
    qual_sk = await client.find_session_key(
        year=2026,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name="Qualifying",
    )
    return ActiveWeekend(
        circuit_key=weekend.circuit_key,
        display_name=weekend.display_name,
        openf1_circuit_name=circuit.openf1_circuit_name,
        year=2026,
        race_session_key=race_sk,
        qualifying_session_key=qual_sk,
        meeting_key=None,
        race_start=weekend.race_utc,
    )


async def generate_picks_for_weekend(
    weekend: RaceWeekend,
    *,
    client: OpenF1Client,
    agent: RadioInterceptAgent,
    vector_store: MockVectorStore,
    settings: PitWallSettings,
    phone: str | None = None,
    persist_picks: bool = True,
    refresh_practice: bool = False,
    ctx: OrchestratorContext | None = None,
) -> PickOutput:
    """
    Generate picks for a calendar race weekend.

    Loads practice signals from DB unless refresh_practice is True.
    """
    orchestrator = ctx or get_orchestrator_context()
    profile_key = profile_circuit_key(weekend.circuit_key)
    circuit = get_circuit_profile(profile_key)
    if circuit is None:
        raise ValueError(f"No circuit profile for {profile_key}")

    active = await _resolve_openf1_weekend(client, weekend, circuit)

    if refresh_practice:
        practice_signals = await analyze_practice_weekend(
            client=client,
            agent=agent,
            vector_store=vector_store,
            circuit=circuit,
            year=2026,
            persist=True,
        )
    else:
        session_key = active.qualifying_session_key or active.race_session_key or 0
        practice_signals = await load_practice_signals(session_key, circuit_key=profile_key)
        if not practice_signals:
            practice_signals = await analyze_practice_weekend(
                client=client,
                agent=agent,
                vector_store=vector_store,
                circuit=circuit,
                year=2026,
                persist=True,
            )

    qualifying = []
    if active.qualifying_session_key is not None:
        qualifying = await build_qualifying_rows(client, active.qualifying_session_key)

    weather_forecast = None
    weather_sk = active.qualifying_session_key or active.race_session_key
    if weather_sk is not None:
        samples = await client.get_weather(weather_sk)
        if samples:
            weather_forecast = build_weather_forecast(weather_sk, samples)

    user_team = await get_fantasy_team(phone) if phone else None
    await predict_price_changes(weekend.race_key, circuit.openf1_circuit_name)
    price_predictions = await get_price_prediction_map(weekend.race_key)

    generator_input = PickGeneratorInput(
        circuit=circuit,
        practice_signals=practice_signals,
        qualifying_result=qualifying,
        weather_forecast=weather_forecast,
        user_team=user_team,
        price_predictions=price_predictions,
        race_key=weekend.race_key,
        generated_by=_generated_by_label(settings),
    )

    output = generate_picks(generator_input)
    if persist_picks:
        await append_picks(
            weekend.race_key,
            output,
            phone=phone,
            circuit_key=weekend.circuit_key,
        )
    return output
