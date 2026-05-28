"""Agent 1 — Context Builder (Thursday pre-weekend)."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger

from agents.base import AgentOutput, AgentRunDependencies
from circuits.profiles import CircuitProfile
from intelligence.constructor_strategy import build_constructor_strategy_profiles
from intelligence.repository import upsert_constructor_strategy_rows
from intelligence.schemas import WeatherForecast
from openf1.client import OpenF1Client
from orchestrator.race_context import ChampionshipRow, evolve_race_context, RaceContext

# Circuit lat/lon for Open-Meteo (approximate)
_CIRCUIT_COORDS: dict[str, tuple[float, float]] = {
    "bahrain": (26.0325, 50.5106),
    "jeddah": (21.6319, 39.1044),
    "melbourne": (-37.8497, 144.968),
    "suzuka": (34.8431, 136.541),
    "shanghai": (31.3389, 121.22),
    "miami": (25.958, -80.2389),
    "imola": (44.3439, 11.7167),
    "monaco": (43.7347, 7.4206),
    "barcelona": (41.57, 2.2611),
    "madrid": (40.4653, -3.6167),
    "montreal": (45.5, -73.5228),
    "spielberg": (47.2197, 14.7647),
    "silverstone": (52.0786, -1.0169),
    "spa": (50.4372, 5.9714),
    "hungaroring": (47.5789, 19.2486),
    "zandvoort": (52.3888, 4.5409),
    "monza": (45.6156, 9.2811),
    "baku": (40.3725, 49.8533),
    "marina_bay": (1.2914, 103.864),
    "austin": (30.1328, -97.6411),
    "mexico_city": (19.4042, -99.0907),
    "interlagos": (-23.7036, -46.6997),
    "las_vegas": (36.1147, -115.173),
    "lusail": (25.49, 51.454),
    "yas_marina": (24.4672, 54.603),
}

_FIA_URL = "https://www.fia.com/documents"


class ContextBuilderOutput(AgentOutput):
    """Agent 1 completion summary."""

    duration_s: float
    fia_count: int
    drivers_loaded: int


async def run_context_builder(
    ctx: RaceContext,
    deps: AgentRunDependencies,
) -> RaceContext:
    """
    Build championship, weather, circuit intel, and FIA bulletin context.

    Target: under 90 seconds (enforced by orchestrator budget).
    """
    started = datetime.now(tz=UTC)
    client = deps.openf1_client
    circuit = ctx.circuit_profile
    profile_key = ctx.race_weekend.circuit_key

    championship, circuit_intel, weather, fia = await asyncio.gather(
        _load_championship(client),
        _load_circuit_intel(client, circuit),
        _fetch_open_meteo(profile_key),
        _scrape_fia_titles(circuit.openf1_circuit_name, circuit.display_name),
        return_exceptions=True,
    )

    updates: dict[str, Any] = {}
    if isinstance(championship, dict):
        updates["championship_snapshot"] = championship
    else:
        logger.warning("Championship load failed: {}", championship)

    if isinstance(circuit_intel, dict):
        updates["circuit_intel"] = circuit_intel
    else:
        logger.warning("Circuit intel failed: {}", circuit_intel)

    if isinstance(weather, WeatherForecast):
        updates["weather_forecast"] = weather
    elif weather is not None:
        logger.warning("Open-Meteo failed: {}", weather)

    if isinstance(fia, list):
        updates["fia_bulletins"] = fia
    else:
        logger.warning("FIA scrape failed: {}", fia)
        updates["fia_bulletins"] = []

    new_ctx = evolve_race_context(ctx, **updates)
    elapsed = (datetime.now(tz=UTC) - started).total_seconds()
    logger.bind(race_key=ctx.race_weekend.race_key, elapsed_s=round(elapsed, 1)).info(
        "Agent 1 context builder complete"
    )
    return new_ctx


async def _load_championship(client: OpenF1Client) -> dict[str, ChampionshipRow]:
    """Derive WDC snapshot and championship pressure from latest race results."""
    sessions = await client.get_sessions(year=2026, session_name="Race")
    if not sessions:
        return {}

    latest = max(sessions, key=lambda s: s.date_start or datetime.min.replace(tzinfo=UTC))
    results = await client.get_session_results(latest.session_key)
    points_table: dict[str, float] = {}
    from intelligence.drivers import driver_code_for

    for row in results:
        if row.position is None:
            continue
        code = driver_code_for(row.driver_number)
        from fantasy.rules import driver_points_race

        pts = float(driver_points_race(row.position, classified=row.position <= 20))
        points_table[code] = points_table.get(code, 0.0) + pts

    sorted_drivers = sorted(points_table.items(), key=lambda x: x[1], reverse=True)
    snapshot: dict[str, ChampionshipRow] = {}
    leader_pts = sorted_drivers[0][1] if sorted_drivers else 0.0
    for idx, (code, pts) in enumerate(sorted_drivers[:22], start=1):
        gap = leader_pts - pts
        if idx == 1:
            pressure = 0.3
        elif gap < 25:
            pressure = 0.8
        elif pts < 50:
            pressure = 0.1
        else:
            pressure = 0.5
        snapshot[code] = ChampionshipRow(
            driver_code=code,
            position=idx,
            points=pts,
            championship_pressure=pressure,
        )
    return snapshot


async def _load_circuit_intel(
    client: OpenF1Client,
    circuit: CircuitProfile,
) -> dict[str, Any]:
    """Historical race analysis — last 5 races at this circuit."""
    gains: list[int] = []
    sc_count = 0
    races = 0
    for year in range(2021, 2026):
        sk = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name="Race",
        )
        if sk is None:
            continue
        results = await client.get_session_results(sk)
        if not results:
            continue
        races += 1
        positions = sorted(
            [r.position for r in results if r.position is not None],
        )
        if len(positions) >= 5:
            p5 = positions[4]
            p20 = positions[-1] if len(positions) >= 20 else positions[-1]
            gains.append(max(0, p20 - p5))
        rc = await client.get_race_control(sk)
        if any((m.message or "").upper().find("SAFETY CAR") >= 0 for m in rc):
            sc_count += 1

    avg_gain = sum(gains) / len(gains) if gains else circuit.positions_gained_ceiling
    sc_prob = sc_count / races if races else circuit.safety_car_probability
    strategy_profiles = await build_constructor_strategy_profiles(client, circuit)
    strategy_rows = [
        {
            "constructor_code": p.constructor_code,
            "sample_races": p.sample_races,
            "lead_window_samples": p.lead_window_samples,
            "early_pit_count": p.early_pit_count,
            "early_pit_rate": p.early_pit_rate,
            "undercut_attempts": p.undercut_attempts,
            "undercut_successes": p.undercut_successes,
            "undercut_success_rate": p.undercut_success_rate,
            "hedge_events": p.hedge_events,
            "hedge_rate": p.hedge_rate,
        }
        for p in strategy_profiles
    ]
    if strategy_rows:
        await upsert_constructor_strategy_rows(circuit.circuit_key, strategy_rows)

    strategy_summary: list[str] = []
    for p in sorted(strategy_profiles, key=lambda x: x.early_pit_rate, reverse=True)[:3]:
        if p.lead_window_samples < 3:
            continue
        strategy_summary.append(
            (
                f"{p.constructor_code}: pits early in lead-fight windows "
                f"{p.early_pit_count}/{p.lead_window_samples} races "
                f"({int(round(p.early_pit_rate * 100))}%)"
            )
        )
    return {
        "avg_positions_gained_top5": round(avg_gain, 1),
        "safety_car_probability_observed": round(sc_prob, 2),
        "sample_races": races,
        "typical_strategy": "2-stop" if circuit.tire_deg_rate > 0.65 else "1-stop",
        "constructor_strategy_profiles": {
            p.constructor_code: {
                "sample_races": p.sample_races,
                "lead_window_samples": p.lead_window_samples,
                "early_pit_count": p.early_pit_count,
                "early_pit_rate": p.early_pit_rate,
                "undercut_attempts": p.undercut_attempts,
                "undercut_successes": p.undercut_successes,
                "undercut_success_rate": p.undercut_success_rate,
                "hedge_events": p.hedge_events,
                "hedge_rate": p.hedge_rate,
            }
            for p in strategy_profiles
        },
        "constructor_strategy_summary": strategy_summary,
    }


async def _fetch_open_meteo(circuit_key: str) -> WeatherForecast | None:
    """72hr forecast from Open-Meteo (no API key)."""
    coords = _CIRCUIT_COORDS.get(circuit_key)
    if coords is None:
        return None
    lat, lon = coords
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,wind_speed_10m",
        "forecast_days": 3,
    }
    async with httpx.AsyncClient(timeout=20.0) as http:
        resp = await http.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})
    temps = hourly.get("temperature_2m", [])
    rain_probs = hourly.get("precipitation_probability", [])
    wind = hourly.get("wind_speed_10m", [])
    rain_probability = max(rain_probs) / 100.0 if rain_probs else 0.0
    temp_range = (min(temps), max(temps)) if temps else (None, None)
    summary = (
        f"Rain probability {rain_probability:.0%}; "
        f"temp {temp_range[0]:.0f}–{temp_range[1]:.0f}°C; "
        f"wind to {max(wind):.0f} km/h"
        if temps and wind
        else "Forecast unavailable"
    )
    return WeatherForecast(
        session_key=0,
        rainfall_likely=rain_probability > 0.35,
        air_temperature_c=float(sum(temps) / len(temps)) if temps else None,
        track_temperature_c=None,
        summary=summary[:240],
    )


async def _scrape_fia_titles(circuit_name: str, display_name: str) -> list[str]:
    """
    Parse FIA document listing titles only — never PDF content.

    Returns plain-English summaries; empty list on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as http:
            resp = await http.get(_FIA_URL)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        logger.warning("FIA document scrape failed: {}", exc)
        return []

    titles = re.findall(r"<a[^>]*>([^<]{10,120})</a>", html, flags=re.IGNORECASE)
    circuit_tokens = {circuit_name.lower(), display_name.lower(), "technical directive", "bulletin"}
    summaries: list[str] = []
    for title in titles[:80]:
        clean = re.sub(r"\s+", " ", title).strip()
        lower = clean.lower()
        if any(tok in lower for tok in circuit_tokens):
            summaries.append(f"FIA document noted this week: {clean[:100]}")
    return summaries[:5]
