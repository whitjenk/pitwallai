"""Deterministic, zero-LLM radio decoder using vector retrieval and pattern rules."""

from __future__ import annotations

import asyncio
import re
import time
from collections import Counter

from pitwallai.agents.radio_intercept.decode_utils import finalize_transmission
from pitwallai.agents.radio_intercept.enums import RadioIntent, StrategicSignal, UrgencyLevel
from pitwallai.agents.radio_intercept.models import (
    AgentDependencies,
    DecodedTransmission,
    HistoricalRadio,
    JargonEntry,
    RadioRawMessage,
)

_INTENT_PATTERNS: list[tuple[RadioIntent, re.Pattern[str]]] = [
    (RadioIntent.PIT_CALL, re.compile(r"\b(box|pit\s+confirm|multi\s*21|box\s+box)\b", re.I)),
    (RadioIntent.TIRE_COMPLAINT, re.compile(r"\b(tyres?\s+are\s+gone|graining|blistering|no\s+grip|dead)\b", re.I)),
    (RadioIntent.PUSH_MODE, re.compile(r"\b(push|deploy|maximum\s+attack|full\s+ers)\b", re.I)),
    (RadioIntent.CONSERVE_MODE, re.compile(r"\b(stay\s+out|conserve|lift\s+and\s+coast|going\s+long)\b", re.I)),
    (RadioIntent.ENGINE_MODE_CHANGE, re.compile(r"\b(engine\s+mode|harvest|mode\s+\d+)\b", re.I)),
    (RadioIntent.SAFETY_CAR_RESPONSE, re.compile(r"\b(safety\s+car|vsc|virtual\s+safety)\b", re.I)),
    (RadioIntent.WEATHER_QUERY, re.compile(r"\b(weather|rain|spots|drizzle)\b", re.I)),
    (RadioIntent.MECHANICAL_ISSUE, re.compile(r"\b(something\s+feels\s+wrong|mechanical|snap|overheating)\b", re.I)),
    (RadioIntent.GAP_UPDATE_REQUEST, re.compile(r"\b(gap|interval|delta|closing)\b", re.I)),
    (RadioIntent.FUEL_MANAGEMENT, re.compile(r"\b(fuel\s+saving|fuel)\b", re.I)),
    (RadioIntent.DRS_ISSUE, re.compile(r"\b(drs)\b", re.I)),
    (RadioIntent.DRIVER_FRUSTRATION, re.compile(r"\b(ridiculous|killing\s+me|cannot\s+push)\b", re.I)),
]

_INTENT_TO_SIGNAL: dict[RadioIntent, StrategicSignal] = {
    RadioIntent.PIT_CALL: StrategicSignal.IMMINENT_PIT_WINDOW,
    RadioIntent.TIRE_COMPLAINT: StrategicSignal.TIRE_DEGRADATION_HIGH,
    RadioIntent.PUSH_MODE: StrategicSignal.PACE_MODE_SHIFT,
    RadioIntent.CONSERVE_MODE: StrategicSignal.OVERCUT_ATTEMPT,
    RadioIntent.ENGINE_MODE_CHANGE: StrategicSignal.PACE_MODE_SHIFT,
    RadioIntent.SAFETY_CAR_RESPONSE: StrategicSignal.SAFETY_CAR_STRATEGY,
    RadioIntent.MECHANICAL_ISSUE: StrategicSignal.RELIABILITY_RISK,
    RadioIntent.DRS_ISSUE: StrategicSignal.RELIABILITY_RISK,
    RadioIntent.GAP_UPDATE_REQUEST: StrategicSignal.NEUTRAL,
    RadioIntent.FUEL_MANAGEMENT: StrategicSignal.NEUTRAL,
    RadioIntent.DRIVER_FRUSTRATION: StrategicSignal.TIRE_DEGRADATION_HIGH,
    RadioIntent.WEATHER_QUERY: StrategicSignal.NEUTRAL,
    RadioIntent.UNKNOWN: StrategicSignal.UNKNOWN,
}


def _pattern_intent(transcript: str) -> RadioIntent | None:
    """Return first intent matched by keyword patterns."""
    for intent, pattern in _INTENT_PATTERNS:
        if pattern.search(transcript):
            return intent
    return None


def _vote_intent(historical: list[HistoricalRadio], transcript: str) -> tuple[RadioIntent, StrategicSignal, float]:
    """
    Combine vector-neighbor voting with pattern overrides.

    Returns:
        Tuple of (intent, signal, confidence).
    """
    pattern_hit = _pattern_intent(transcript)
    if not historical:
        intent = pattern_hit or RadioIntent.UNKNOWN
        return intent, _INTENT_TO_SIGNAL.get(intent, StrategicSignal.UNKNOWN), 0.35 if pattern_hit else 0.2

    weighted: Counter[RadioIntent] = Counter()
    signal_weighted: Counter[StrategicSignal] = Counter()
    top_similarity = historical[0].similarity_score

    for record in historical:
        weight = max(record.similarity_score, 0.0)
        weighted[record.decoded_intent] += weight
        signal_weighted[record.strategic_signal] += weight

    intent = weighted.most_common(1)[0][0]
    signal = signal_weighted.most_common(1)[0][0]

    if pattern_hit is not None and pattern_hit != intent and top_similarity < 0.82:
        intent = pattern_hit
        signal = _INTENT_TO_SIGNAL.get(intent, signal)

    confidence = min(0.98, max(0.4, top_similarity * 0.7 + (0.25 if pattern_hit else 0.0)))
    return intent, signal, confidence


async def _extract_jargon(deps: AgentDependencies, transcript: str) -> list[JargonEntry]:
    """Find glossary terms present in the transcript."""
    lowered = transcript.lower()
    terms: list[str] = []
    for term in sorted(deps.jargon_glossary, key=len, reverse=True):
        if term.lower() in lowered:
            terms.append(term)
    if not terms:
        return []
    glossary = {k.lower(): v for k, v in deps.jargon_glossary.items()}
    return [
        JargonEntry(
            term=term,
            plain_english=glossary.get(term.lower(), "UNKNOWN"),
            confidence=0.9,
        )
        for term in terms[:8]
    ]


def _build_evidence_summary(
    transcript: str,
    historical: list[HistoricalRadio],
    intent: RadioIntent,
) -> str | None:
    """Template evidence string from nearest historical precedent."""
    if not historical:
        return None
    top = historical[0]
    return (
        f"Transcript aligns with historical {intent.value} precedent "
        f"(doc {top.doc_id}, similarity {top.similarity_score:.2f}). "
        f"Prior outcome: {top.outcome or 'unknown'}."
    )


def _build_reasoning(
    transcript: str,
    historical: list[HistoricalRadio],
    intent: RadioIntent,
    signal: StrategicSignal,
) -> str:
    """Short reasoning block without LLM."""
    if historical:
        top = historical[0]
        return (
            f"Heard: '{transcript[:120]}'. "
            f"Nearest precedent {top.doc_id} ({top.similarity_score:.0%} match) suggests "
            f"{intent.value} / {signal.value}."
        )
    return f"Heard: '{transcript[:120]}'. Pattern rules classified as {intent.value}."


class RulesDecoder:
    """
    Fast local decoder: embedding retrieval + weighted vote + regex patterns.

    Typical latency: 5–80 ms (no network). No API keys required.
    """

    async def decode(
        self,
        message: RadioRawMessage,
        deps: AgentDependencies,
    ) -> DecodedTransmission:
        """
        Decode a transmission without calling an LLM.

        Args:
            message: Raw radio message.
            deps: Shared agent dependencies.

        Returns:
            Fully populated DecodedTransmission.
        """
        started = time.perf_counter()
        transcript = message.raw_transcript.strip()

        historical = await asyncio.to_thread(
            deps.vector_store.query,
            transcript,
            deps.max_context_results,
        )
        intent, signal, confidence = _vote_intent(historical, transcript)
        if confidence < 0.4:
            intent = RadioIntent.UNKNOWN
            signal = StrategicSignal.UNKNOWN

        jargon = await _extract_jargon(deps, transcript)
        context_ids = [record.doc_id for record in historical[: deps.max_context_results]]
        evidence = _build_evidence_summary(transcript, historical, intent)
        reasoning = _build_reasoning(transcript, historical, intent, signal)

        draft = DecodedTransmission(
            session_key=message.session_key,
            driver_number=message.driver_number,
            driver_code=message.driver_code,
            team=message.team,
            timestamp=message.timestamp,
            raw_transcript=transcript,
            decoded_intent=intent,
            jargon_decoded=jargon,
            strategic_signal=signal,
            urgency_level=UrgencyLevel.from_intent(intent),
            confidence_score=confidence,
            competitor_intel=None,
            evidence_summary=evidence,
            context_doc_ids=context_ids,
            model_reasoning=reasoning,
            lap_number=message.lap_number,
        )
        return finalize_transmission(draft, message, deps, started)
