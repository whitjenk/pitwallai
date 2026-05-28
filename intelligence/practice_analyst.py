"""Practice Analyst — FP1/FP2 radio sentiment and anomaly detection."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean

from loguru import logger

from circuits.profiles import CircuitProfile
from intelligence.drivers import driver_code_for, team_for_driver
from intelligence.repository import save_practice_signals
from intelligence.schemas import PracticeSignal
from openf1.client import OpenF1Client
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal, UrgencyLevel
from pitwallai.agents.radio_intercept.models import AgentDependencies, DecodedTransmission, RadioRawMessage
from pitwallai.agents.radio_intercept.seed_data import JARGON_GLOSSARY, TEAM_COLORS
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

_PRACTICE_SESSION_NAMES = ("Practice 1", "Practice 2")
_TEAMMATE_GAP_THRESHOLD = 0.5
_TEAMMATE_GAP_PRIOR_MAX = 0.2
_SENTIMENT_DROP_THRESHOLD = 0.4
_MIN_LONG_RUN_LAPS = 5


def _transmission_to_signal(
    decoded: DecodedTransmission,
    *,
    session_label: str,
) -> PracticeSignal:
    """
    Map DecodedTransmission to PracticeSignal using rules-path heuristics.

    Uses evidence_summary (observation-only contract) — does not modify decoder.
    """
    mechanical: list[str] = []
    if decoded.decoded_intent == RadioIntent.TIRE_COMPLAINT:
        mechanical.append("tyre_issue")
    if decoded.decoded_intent == RadioIntent.MECHANICAL_ISSUE:
        mechanical.append("mechanical")
    if decoded.strategic_signal == StrategicSignal.TIRE_DEGRADATION_HIGH:
        mechanical.append("high_degradation")
    if "understeer" in decoded.raw_transcript.lower():
        mechanical.append("understeer")
    if "oversteer" in decoded.raw_transcript.lower():
        mechanical.append("oversteer")
    if "brake" in decoded.raw_transcript.lower():
        mechanical.append("brake_bias")

    urgency = decoded.urgency_level
    if urgency in (UrgencyLevel.CRITICAL, UrgencyLevel.HIGH) and decoded.decoded_intent in (
        RadioIntent.TIRE_COMPLAINT,
        RadioIntent.MECHANICAL_ISSUE,
        RadioIntent.DRIVER_FRUSTRATION,
    ):
        setup_sentiment = -0.75
    elif decoded.decoded_intent in (RadioIntent.PUSH_MODE, RadioIntent.GAP_UPDATE_REQUEST):
        setup_sentiment = 0.35
    elif decoded.decoded_intent == RadioIntent.CONSERVE_MODE:
        setup_sentiment = -0.15
    else:
        setup_sentiment = 0.1

    tire_confidence = max(0.15, 1.0 - (0.25 * len(mechanical)))
    pace_satisfaction = 0.75 if decoded.decoded_intent == RadioIntent.PUSH_MODE else 0.45
    if decoded.confidence_score < 0.5:
        pace_satisfaction *= 0.8

    evidence_bits: list[str] = []
    if decoded.evidence_summary:
        evidence_bits.append(decoded.evidence_summary)
    evidence_bits.append(decoded.raw_transcript[:200])

    return PracticeSignal(
        driver_number=decoded.driver_number,
        driver_code=decoded.driver_code,
        session=session_label,
        setup_sentiment=round(max(-1.0, min(1.0, setup_sentiment)), 3),
        tire_confidence=round(max(0.0, min(1.0, tire_confidence)), 3),
        mechanical_flags=mechanical,
        pace_satisfaction=round(max(0.0, min(1.0, pace_satisfaction)), 3),
        anomaly_flags=[],
        raw_evidence=evidence_bits,
    )


async def _decode_session_radio(
    client: OpenF1Client,
    agent: RadioInterceptAgent,
    deps: AgentDependencies,
    session_key: int,
    session_label: str,
) -> list[PracticeSignal]:
    """Fetch and decode all team radio for one practice session."""
    entries = await client.get_team_radio(session_key)
    by_driver: dict[int, list] = defaultdict(list)
    for entry in entries:
        if entry.raw_transcript:
            by_driver[entry.driver_number].append(entry)

    signals: list[PracticeSignal] = []
    for driver_number, radios in by_driver.items():
        excerpts: list[str] = []
        sentiments: list[float] = []
        tire_scores: list[float] = []
        pace_scores: list[float] = []
        mechanical: list[str] = []

        for entry in radios[-6:]:
            message = RadioRawMessage(
                session_key=session_key,
                driver_number=driver_number,
                driver_code=driver_code_for(driver_number),
                team=team_for_driver(driver_code_for(driver_number)),
                timestamp=entry.date or datetime.now(tz=UTC),
                raw_transcript=entry.raw_transcript,
            )
            decoded = await agent.decode(message, deps)
            sig = _transmission_to_signal(decoded, session_label=session_label)
            sentiments.append(sig.setup_sentiment)
            tire_scores.append(sig.tire_confidence)
            pace_scores.append(sig.pace_satisfaction)
            mechanical.extend(sig.mechanical_flags)
            excerpts.extend(sig.raw_evidence)

        if not sentiments:
            continue

        signals.append(
            PracticeSignal(
                driver_number=driver_number,
                driver_code=driver_code_for(driver_number),
                session=session_label,
                setup_sentiment=round(mean(sentiments), 3),
                tire_confidence=round(mean(tire_scores), 3),
                mechanical_flags=sorted(set(mechanical)),
                pace_satisfaction=round(mean(pace_scores), 3),
                anomaly_flags=[],
                raw_evidence=excerpts[:8],
            )
        )
    return signals


def _best_lap_by_driver(laps: list) -> dict[int, float]:
    """Return best lap duration per driver."""
    best: dict[int, float] = {}
    for lap in laps:
        if lap.lap_duration is None or lap.is_pit_out_lap:
            continue
        current = best.get(lap.driver_number)
        if current is None or lap.lap_duration < current:
            best[lap.driver_number] = lap.lap_duration
    return best


def _teammate_pairs(driver_numbers: set[int]) -> list[tuple[int, int]]:
    """Approximate teammate pairs by team (hardcoded 2025)."""
    teams: dict[str, list[int]] = {
        "RBR": [1, 11],
        "FER": [16, 55],
        "MCL": [4, 81],
        "MER": [44, 63],
        "AM": [14, 18],
        "ALP": [10, 31],
        "WIL": [23, 2],
        "RB": [22, 3],
        "HAA": [27, 20],
        "SAU": [77, 24],
    }
    pairs: list[tuple[int, int]] = []
    for members in teams.values():
        present = [d for d in members if d in driver_numbers]
        if len(present) == 2:
            pairs.append((present[0], present[1]))
    return pairs


async def _prior_year_teammate_gaps(
    client: OpenF1Client,
    *,
    circuit: CircuitProfile,
    session_name: str,
    year: int,
) -> dict[tuple[int, int], float]:
    """
    Best-lap teammate gaps from the prior year at the same circuit/session.

    Returns:
        Mapping of sorted driver pair → gap in seconds.
    """
    prior_sk = await client.find_session_key(
        year=year - 1,
        circuit_short_name=circuit.openf1_circuit_name,
        session_name=session_name,
    )
    if prior_sk is None:
        return {}
    laps = await client.get_laps(prior_sk)
    best = _best_lap_by_driver(laps)
    gaps: dict[tuple[int, int], float] = {}
    for d1, d2 in _teammate_pairs(set(best.keys())):
        if d1 in best and d2 in best:
            pair = (min(d1, d2), max(d1, d2))
            gaps[pair] = abs(best[d1] - best[d2])
    return gaps


async def _apply_anomalies(
    signals: list[PracticeSignal],
    *,
    circuit: CircuitProfile,
    session_keys: dict[str, int],
    client: OpenF1Client,
    current_year: int,
) -> list[PracticeSignal]:
    """Run anomaly detection after FP1+FP2 scoring."""
    by_driver_session: dict[tuple[int, str], PracticeSignal] = {
        (s.driver_number, s.session): s for s in signals
    }
    fp1 = [s for s in signals if s.session == "FP1"]
    fp2 = [s for s in signals if s.session == "FP2"]

    # Sentiment drop FP1 → FP2
    fp1_map = {s.driver_number: s for s in fp1}
    for sig in fp2:
        flags = list(sig.anomaly_flags)
        prior = fp1_map.get(sig.driver_number)
        if prior and prior.setup_sentiment - sig.setup_sentiment > _SENTIMENT_DROP_THRESHOLD:
            flags.append("sentiment_drop_fp1_fp2")
        by_driver_session[(sig.driver_number, sig.session)] = sig.model_copy(
            update={"anomaly_flags": flags}
        )

    session_name_map = {"FP1": "Practice 1", "FP2": "Practice 2"}

    for label, sk in session_keys.items():
        laps = await client.get_laps(sk)
        best = _best_lap_by_driver(laps)
        drivers = set(best.keys())
        openf1_name = session_name_map.get(label, label)

        for d1, d2 in _teammate_pairs(drivers):
            if d1 not in best or d2 not in best:
                continue
            gap = abs(best[d1] - best[d2])
            if gap > _TEAMMATE_GAP_THRESHOLD:
                for driver in (d1, d2):
                    key = (driver, label)
                    if key in by_driver_session:
                        sig = by_driver_session[key]
                        flags = list(sig.anomaly_flags) + [f"teammate_gap_{gap:.2f}s_{label}"]
                        by_driver_session[key] = sig.model_copy(update={"anomaly_flags": flags})

        prior_gaps = await _prior_year_teammate_gaps(
            client,
            circuit=circuit,
            session_name=openf1_name,
            year=current_year,
        )
        for d1, d2 in _teammate_pairs(drivers):
            if d1 not in best or d2 not in best:
                continue
            pair = (min(d1, d2), max(d1, d2))
            prior_gap = prior_gaps.get(pair)
            if prior_gap is None:
                continue
            gap = abs(best[d1] - best[d2])
            if gap > _TEAMMATE_GAP_THRESHOLD and prior_gap < _TEAMMATE_GAP_PRIOR_MAX:
                for driver in (d1, d2):
                    key = (driver, label)
                    if key in by_driver_session:
                        sig = by_driver_session[key]
                        flags = list(sig.anomaly_flags) + ["historical_teammate_gap_shift"]
                        by_driver_session[key] = sig.model_copy(update={"anomaly_flags": flags})

        by_driver_laps: dict[int, list] = defaultdict(list)
        for lap in laps:
            if lap.lap_duration is not None and not lap.is_pit_out_lap:
                by_driver_laps[lap.driver_number].append(lap)
        team_expected = max((len(v) for v in by_driver_laps.values()), default=0) * 0.6
        for driver, driver_laps in by_driver_laps.items():
            if len(driver_laps) < max(_MIN_LONG_RUN_LAPS, team_expected):
                key = (driver, label)
                if key in by_driver_session:
                    sig = by_driver_session[key]
                    flags = list(sig.anomaly_flags) + ["short_long_run_count"]
                    by_driver_session[key] = sig.model_copy(update={"anomaly_flags": flags})

    return list(by_driver_session.values())


async def analyze_practice_weekend(
    *,
    client: OpenF1Client,
    agent: RadioInterceptAgent,
    vector_store: MockVectorStore,
    circuit: CircuitProfile,
    year: int,
    persist: bool = True,
) -> list[PracticeSignal]:
    """
    Process FP1 and FP2 radio through the existing decode pipeline.

    Does not modify RadioInterceptDecoder — uses RadioInterceptAgent.decode().

    Args:
        client: OpenF1 client.
        agent: Decoder agent (rules or LLM).
        vector_store: Seeded vector store.
        circuit: Injected circuit profile.
        year: Championship year.
        persist: Save signals to Postgres.

    Returns:
        PracticeSignal list for FP1 and FP2 combined (with anomaly_flags).
    """
    deps = AgentDependencies(
        vector_store=vector_store,
        session_key=0,
        jargon_glossary=JARGON_GLOSSARY,
        team_colors=TEAM_COLORS,
    )

    session_keys: dict[str, int] = {}
    all_signals: list[PracticeSignal] = []

    for name in _PRACTICE_SESSION_NAMES:
        sk = await client.find_session_key(
            year=year,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name=name,
        )
        if sk is None:
            logger.warning("Practice session not found: {} {}", circuit.display_name, name)
            continue
        label = "FP1" if "1" in name else "FP2"
        session_keys[label] = sk
        session_signals = await _decode_session_radio(client, agent, deps, sk, label)
        all_signals.extend(session_signals)

    if not all_signals:
        return []

    all_signals = await _apply_anomalies(
        all_signals,
        circuit=circuit,
        session_keys=session_keys,
        client=client,
        current_year=year,
    )

    if persist and session_keys:
        primary_key = next(iter(session_keys.values()))
        await save_practice_signals(primary_key, circuit.circuit_key, all_signals)

    logger.bind(circuit=circuit.circuit_key, signals=len(all_signals)).info(
        "Practice analysis complete"
    )
    return all_signals
