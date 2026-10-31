"""Single source of truth for race_key strings across agents and scheduler."""

from __future__ import annotations


def make_race_key(year: int, circuit_key: str, *, round_number: int | None = None) -> str:
    """
    Canonical race_key used by calendar, orchestrator, and persistence.

    Format: ``{year}_{circuit_slug}`` (e.g. ``2026_monaco``, ``2024_monaco``).

    ``round_number`` is accepted for call-site clarity but is not part of the key
    string (calendar and historical data use year + circuit only).
    """
    _ = round_number
    return f"{year}_{circuit_key.lower()}"


def parse_race_key(race_key: str) -> tuple[int, str] | None:
    """Split ``year_circuit`` into components, or None if malformed."""
    parts = race_key.split("_", 1)
    if len(parts) != 2:
        return None
    try:
        year = int(parts[0])
    except ValueError:
        return None
    return year, parts[1]
