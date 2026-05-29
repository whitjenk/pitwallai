"""Central feature flags for off-Bet-1 modules.

All default OFF. Bet 1 (Explanation Cards + SHARE) is the only sanctioned
user-facing surface until subscriber data justifies expansion. See
CLAUDE.md "Feature roadmap context".
"""

from __future__ import annotations

import os


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def chips_enabled() -> bool:
    """Chip planner WhatsApp commands and /chips page. Bet — later."""
    return _flag("PITWALL_CHIPS_ENABLED")


def constructor_strategy_enabled() -> bool:
    """WHY CONSTRUCTOR command and seed_constructor_profiles startup hook."""
    return _flag("PITWALL_CONSTRUCTOR_STRATEGY_ENABLED")


def counterfactual_recap_enabled() -> bool:
    """Post-race counterfactual broadcast job."""
    return _flag("PITWALL_COUNTERFACTUAL_ENABLED")


def season_recap_enabled() -> bool:
    """SEASON command and /season/* HTTP routes."""
    return _flag("PITWALL_SEASON_RECAP_ENABLED")


def budget_transfers_enabled() -> bool:
    """BUDGET and TRANSFERS commands."""
    return _flag("PITWALL_BUDGET_TRANSFERS_ENABLED")


def community_aggregate_enabled() -> bool:
    """Community aggregate broadcast job."""
    return _flag("PITWALL_COMMUNITY_AGGREGATE_ENABLED")


def screenshot_onboarding_enabled() -> bool:
    """Screenshot-based team onboarding (Bet 1 activation reducer)."""
    return _flag("PITWALL_SCREENSHOT_ONBOARDING_ENABLED", default=True)


def low_conviction_mode_enabled() -> bool:
    """Switch Saturday broadcast to honest "hold transfers" message when
    signals are sparse or uncertain. Brand-defining; default ON."""
    return _flag("PITWALL_LOW_CONVICTION_MODE_ENABLED", default=True)


def friday_what_changed_enabled() -> bool:
    """Friday "what changed since last broadcast" digest. Scaffolded; default OFF
    until calibration data accumulates."""
    return _flag("PITWALL_FRIDAY_WHAT_CHANGED_ENABLED")


def monday_league_postmortem_enabled() -> bool:
    """Monday league post-mortem broadcast. Scaffolded; default OFF
    until league-standings screenshots accumulate."""
    return _flag("PITWALL_MONDAY_POSTMORTEM_ENABLED")
