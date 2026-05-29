"""Confidence-band calibration tracking.

When PitWallAI shows the user *HIGH*, those picks should hit at ≥70%.
*MED* 50-70%. *LOW* <50%. Calibration drift breaks the brand promise.

This module turns scored PickRow rows into a per-band hit rate report.
Caller decides what to do with drift (alert, recalibrate, deprioritize).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from db.models import PickRow


class ConfidenceBand(str, Enum):
    HIGH = "HIGH"
    MED = "MED"
    LOW = "LOW"


# Display thresholds — must match whatsapp.commands._utils.confidence_band.
_HIGH_FLOOR = 70.0
_MED_FLOOR = 50.0

# Target hit rate per band — the brand promise we're calibrating against.
TARGET_HIT_RATE: dict[ConfidenceBand, float] = {
    ConfidenceBand.HIGH: 0.70,
    ConfidenceBand.MED: 0.55,
    ConfidenceBand.LOW: 0.40,
}


def band_for_confidence(confidence: float) -> ConfidenceBand:
    if confidence >= _HIGH_FLOOR:
        return ConfidenceBand.HIGH
    if confidence >= _MED_FLOOR:
        return ConfidenceBand.MED
    return ConfidenceBand.LOW


@dataclass(frozen=True, slots=True)
class BandReport:
    band: ConfidenceBand
    sample_size: int
    hit_rate: float
    target_hit_rate: float

    @property
    def drift(self) -> float:
        """Positive = beating the target, negative = under-calibrated."""
        return self.hit_rate - self.target_hit_rate

    @property
    def is_well_calibrated(self) -> bool:
        """±5pp band; tighter than that needs a real eval set."""
        return abs(self.drift) <= 0.05


def calibration_report(picks: list[PickRow]) -> list[BandReport]:
    """Compute hit-rate-by-band over a list of scored picks.

    Only picks with ``was_correct`` set are counted. Returns a report per
    band, even if sample_size is 0 — callers benefit from the explicit
    "no data yet" signal.
    """
    buckets: dict[ConfidenceBand, list[bool]] = {b: [] for b in ConfidenceBand}
    for p in picks:
        if p.was_correct is None:
            continue
        buckets[band_for_confidence(p.confidence)].append(bool(p.was_correct))

    reports: list[BandReport] = []
    for band in ConfidenceBand:
        outcomes = buckets[band]
        n = len(outcomes)
        hit_rate = (sum(outcomes) / n) if n else 0.0
        reports.append(BandReport(
            band=band,
            sample_size=n,
            hit_rate=hit_rate,
            target_hit_rate=TARGET_HIT_RATE[band],
        ))
    return reports


def drift_alert(reports: list[BandReport], *, min_sample: int = 10) -> list[BandReport]:
    """Bands with enough samples *and* drift > 5pp. The "investigate this" list."""
    return [r for r in reports if r.sample_size >= min_sample and not r.is_well_calibrated]
