"""Per-window confidence band for chip recommendations.

Each chip window gets a Low/Medium/High tier plus the reasons that drove
it. Bands are heuristic — the tier is driven by input quality (signal
strength, circuit variance, data maturity), not a numerical distribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from circuits.profiles import CircuitProfile
from scheduler.calendar import RaceWeekend


class ConfidenceTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class ChipConvictionAssessment:
    tier: ConfidenceTier
    reasons: tuple[str, ...]


# Score is on the same 0–1 scale as `_score_window` in chip_planner.
_HIGH_SCORE = 0.75
_LOW_SCORE = 0.55

# Track-variance inputs that widen the band.
_WEATHER_VARIANCE = 0.70
_SAFETY_CAR_VARIANCE = 0.60

# Championship-week index past which "race is far out" pulls confidence down.
# 1 = next race, so >5 means roughly more than a month of intervening data.
_FAR_OUT_WEEK = 5


def assess_chip_conviction(
    score: float,
    circuit: CircuitProfile,
    weekend: RaceWeekend,
    championship_week: int,
) -> ChipConvictionAssessment:
    """Return tier + reasons for a single chip window.

    `championship_week` is the 1-based index of this race in the remaining
    calendar — bigger = further out = less data to ground the call.
    """
    reasons: list[str] = []
    demotions = 0

    if score < _LOW_SCORE:
        reasons.append("weak signal vs. other windows")
        demotions += 2
    elif score < _HIGH_SCORE:
        reasons.append("middling signal strength")
        demotions += 1

    if circuit.weather_sensitivity > _WEATHER_VARIANCE:
        reasons.append("weather-sensitive circuit widens outcomes")
        demotions += 1
    if circuit.safety_car_probability > _SAFETY_CAR_VARIANCE:
        reasons.append("high safety-car probability adds variance")
        demotions += 1

    if championship_week > _FAR_OUT_WEEK:
        reasons.append(f"race is {championship_week} weekends out — limited data")
        demotions += 1

    if weekend.is_sprint:
        # Sprint weekends compress practice to FP1 only.
        reasons.append("sprint format — only FP1 before parc fermé")
        demotions += 1

    if demotions >= 3:
        tier = ConfidenceTier.LOW
    elif demotions >= 1:
        tier = ConfidenceTier.MEDIUM
    else:
        tier = ConfidenceTier.HIGH
        reasons.append("strong signal, stable circuit, near-term race")

    return ChipConvictionAssessment(tier=tier, reasons=tuple(reasons))
