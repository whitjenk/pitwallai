"""Shared recap metrics (session quality, momentum vs prior race)."""

from __future__ import annotations

from db.models import PickRow
from scheduler.calendar import CALENDAR_2026

TrendKind = str  # "up" | "down" | "flat" | "none"

# How PitWallAI scores picks after each Grand Prix (see intelligence/scorer.py).
PICK_SCORING_SCOPE = (
    "Driver picks scored vs official F1 Fantasy Grand Prix race points (P1–P10; DNF/NC −20). "
    "Qualifying, sprint, and constructor assets are not included."
)


def hit_rate_pct(picks: list[PickRow]) -> float:
    """Percent of picks marked correct (GP race outcome)."""
    if not picks:
        return 0.0
    correct = sum(1 for p in picks if p.was_correct)
    return 100.0 * correct / len(picks)


def avg_points_delta(picks: list[PickRow]) -> float:
    """Mean actual GP race points delta for scored picks."""
    scored = [float(p.actual_points_delta) for p in picks if p.actual_points_delta is not None]
    if not scored:
        return 0.0
    return sum(scored) / len(scored)


def session_quality_note(picks: list[PickRow]) -> str | None:
    """Compact weekend scorecard for PitWallAI GP pick quality."""
    if not picks:
        return None
    hit = int(round(hit_rate_pct(picks)))
    avg = avg_points_delta(picks)
    sign = "+" if avg >= 0 else ""
    return f"PitWallAI GP picks: {hit}% hit · {sign}{avg:.1f} avg race pts"


def prev_race_key(race_key: str) -> str | None:
    """Previous race on the calendar, if any."""
    keys = [w.race_key for w in CALENDAR_2026]
    if race_key not in keys:
        return None
    idx = keys.index(race_key)
    if idx <= 0:
        return None
    return keys[idx - 1]


def momentum_delta_pp(current_hit_pct: float, prev_hit_pct: float | None) -> int | None:
    """Rounded percentage-point change vs previous race."""
    if prev_hit_pct is None:
        return None
    return int(round(current_hit_pct - prev_hit_pct))


def momentum_trend(delta_pp: int | None) -> TrendKind:
    """
    Classify momentum for accessible UI styling.

    Uses direction + label (not color alone) for color-blind users.
    """
    if delta_pp is None:
        return "none"
    if delta_pp > 0:
        return "up"
    if delta_pp < 0:
        return "down"
    return "flat"


def momentum_suffix(current_hit_pct: float, prev_hit_pct: float | None) -> str:
    """Plain-text momentum suffix for WhatsApp recaps."""
    delta = momentum_delta_pp(current_hit_pct, prev_hit_pct)
    trend = momentum_trend(delta)
    if trend == "none" or delta is None:
        return ""
    if trend == "up":
        return f" · ↑{delta} vs last race"
    if trend == "down":
        return f" · ↓{abs(delta)} vs last race"
    return " · → flat vs last race"
