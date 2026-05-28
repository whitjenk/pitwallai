"""Configuration for picks API and scheduled generation."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PicksSettings:
    """
    Environment-backed picks pipeline settings.

    Attributes:
        auto_enabled: Run background picks generation on an interval.
        interval_seconds: Seconds between scheduled runs.
        race_year: Championship year for OpenF1 session lookup.
        circuit_key_override: Force a circuit_key (skips OpenF1 calendar detection).
    """

    auto_enabled: bool
    interval_seconds: int
    race_year: int
    circuit_key_override: str | None
    api_key: str

    @classmethod
    def from_env(cls, *, mode: str = "rehearsal") -> PicksSettings:
        """
        Load picks settings from the environment.

        Args:
            mode: App mode — live defaults auto picks on; rehearsal defaults off.

        Returns:
            PicksSettings instance.
        """
        default_auto = "true" if mode == "live" else "false"
        auto_raw = os.getenv("PITWALL_PICKS_AUTO", default_auto).strip().lower()
        auto_enabled = auto_raw in ("1", "true", "yes", "on")

        interval = max(300, int(os.getenv("PITWALL_PICKS_INTERVAL_SECONDS", "1800")))
        year = int(os.getenv("PITWALL_RACE_YEAR", str(os.getenv("PITWALL_YEAR", "2026"))))
        override = os.getenv("PITWALL_CIRCUIT_KEY", "").strip() or None
        api_key = os.getenv("PITWALL_PICKS_API_KEY", "").strip()

        return cls(
            auto_enabled=auto_enabled,
            interval_seconds=interval,
            race_year=year,
            circuit_key_override=override,
            api_key=api_key,
        )
