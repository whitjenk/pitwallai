"""Factories for signal-cache and explanation tests.

Practice cache (``get_practice_signals``) returns ``PracticeSignal | None``.
Radio cache (``get_radio_signals``) returns ``str | None`` — a decoded snippet,
not a separate model; radio lives in ``PracticeSignal.raw_evidence``.
"""

from __future__ import annotations

from intelligence.schemas import PickRecommendation, PracticeSignal


def make_pick(**kwargs) -> PickRecommendation:
    """Build a ``PickRecommendation`` with required fields filled."""
    base: dict = {
        "rank": 1,
        "headline": "Target NOR",
        "confidence": 72.0,
        "reasoning": "Composite score.",
        "driver_code": "NOR",
    }
    base.update(kwargs)
    return PickRecommendation(**base)


def make_practice(**kwargs) -> PracticeSignal:
    """Build a ``PracticeSignal`` (practice cache row / in-memory signal)."""
    base: dict = {
        "driver_number": 4,
        "driver_code": "NOR",
        "session": "FP2",
        "setup_sentiment": 0.5,
        "tire_confidence": 0.7,
        "mechanical_flags": [],
        "pace_satisfaction": 0.6,
        "anomaly_flags": [],
        "raw_evidence": [],
    }
    base.update(kwargs)
    return PracticeSignal(**base)


def make_radio(snippet: str | None = "balance looks good on the soft") -> str | None:
    """
    Build a radio-cache value (``get_radio_signals`` return type).

    Pass ``None`` to represent a cache miss. Snippet should be the decoded text
    without a ``radio:`` prefix — that prefix belongs in ``raw_evidence`` when
    seeding practice rows (see ``make_practice_with_radio``).
    """
    return snippet


def make_practice_with_radio(
    driver_code: str = "NOR",
    snippet: str = "balance looks good on the soft",
    **kwargs,
) -> PracticeSignal:
    """Practice signal whose ``raw_evidence`` yields a radio snippet via ``_radio_snippet``."""
    return make_practice(
        driver_code=driver_code,
        raw_evidence=[f"radio: {snippet}"],
        **kwargs,
    )


def make_practice_with_gap(gap_s: float, **kwargs) -> PracticeSignal:
    """Practice signal with teammate gap in ``anomaly_flags`` (threshold 0.3s in builder)."""
    kwargs.setdefault("anomaly_flags", [f"teammate_gap_{gap_s:.2f}s_FP2"])
    return make_practice(**kwargs)
