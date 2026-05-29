"""Deterministic pick baselines for the eval harness.

A baseline is a function:
    (race_key, circuit_key, race_year) -> list[BaselinePick]

We compare PitWallAI's recommendations against these. If we don't beat the
simplest ones, the product has no reason to exist. Two baselines ship here:

  * top3_chalk          — pick the three most expensive drivers. The "do
                          nothing smart" floor every tipster must clear.
  * prior_season_winner — pick whoever won (or scored most) the same race
                          last season. The "history is destiny" floor.

External baselines (Reddit consensus, plain-LLM-no-tools) need API/auth
work and will land in a follow-up.
"""

from __future__ import annotations

from dataclasses import dataclass

from fantasy.rules import DRIVER_PRICES_M


@dataclass(frozen=True, slots=True)
class BaselinePick:
    """One driver pick from a baseline. Confidence is informational only."""

    driver_code: str
    rank: int
    rationale: str


def top3_chalk_baseline(_race_key: str, _circuit_key: str) -> list[BaselinePick]:
    """Top 3 drivers by current price. No signal. Pure chalk."""
    ranked = sorted(DRIVER_PRICES_M.items(), key=lambda kv: kv[1], reverse=True)
    return [
        BaselinePick(
            driver_code=code,
            rank=i + 1,
            rationale=f"Price rank {i + 1} (${price:.1f}M)",
        )
        for i, (code, price) in enumerate(ranked[:3])
    ]


def prior_season_winner_baseline(
    circuit_key: str,
    *,
    prior_winners: dict[str, str],
) -> list[BaselinePick]:
    """Pick last season's winner at this circuit, if known.

    Args:
        circuit_key: normalized circuit slug (e.g. "monaco").
        prior_winners: {circuit_key → driver_code} sourced from the
            scoring history. Caller supplies (avoids tight coupling to repo).
    """
    code = prior_winners.get(circuit_key.lower())
    if not code:
        return []
    return [BaselinePick(
        driver_code=code,
        rank=1,
        rationale=f"Won {circuit_key} last season",
    )]


def baseline_hit_rate(picks: list[BaselinePick], positions: dict[str, int]) -> float:
    """Fraction of baseline picks that finished P1-P10. 0.0 if no picks."""
    if not picks:
        return 0.0
    hits = sum(1 for p in picks if (positions.get(p.driver_code, 99) <= 10))
    return hits / len(picks)
