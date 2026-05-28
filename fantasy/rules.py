"""
Official F1 Fantasy rules (2026 season).

Sourced from Formula 1's published game rules and 2026 season updates:
https://fantasy.formula1.com/en/game-rules

Key 2026 changes reflected here:
- $100M budget for 5 drivers + 2 constructors
- $3M minimum asset price floor
- 2 free transfers per race; bank 1 unused (max 3 next race); extra transfers cost 10 pts each
- Net transfer counting (reverts before lock do not consume transfers)
- Sprint DNF/NC penalty reduced to -10 (race remains -20)
- Six one-time chips per season (one chip per race weekend max)
"""

from __future__ import annotations

# ── Squad structure ─────────────────────────────────────────────────────────
DRIVERS_PER_TEAM = 5
CONSTRUCTORS_PER_TEAM = 2
BUDGET_CAP_M = 100.0
MIN_ASSET_PRICE_M = 3.0

# ── Transfers ─────────────────────────────────────────────────────────────────
FREE_TRANSFERS_PER_RACE = 2
MAX_TRANSFERS_WITH_BANK = 3  # 2 free + 1 banked from previous week (use or lose)
PENALTY_EXTRA_TRANSFER_PTS = 10

# Sentinel for Limitless chip only — not a normal weekly allowance
CHIP_LIMITLESS = "limitless"
TRANSFERS_LIMITLESS_SENTINEL = 99

# ── Chips (2026) — one use each per season, max one chip per race weekend ─────
CHIP_NAMES_2026: tuple[str, ...] = (
    "3x_boost",
    "limitless",
    "no_negative",
    "wildcard",
    "autopilot",
    "final_fix",
)

# Legacy aliases stored in DB → canonical chip id
_CHIP_ALIASES: dict[str, str] = {
    "3x_boost": "3x_boost",
    "wildcard": "wildcard",
    "limitless": "limitless",
    "no_negative": "no_negative",
    "autopilot": "autopilot",
    "final_fix": "final_fix",
}

# ── Driver race points (Grand Prix) — positions 1–10 score ─────────────────
# Official scale: 25, 18, 15, 12, 10, 8, 6, 4, 2, 1
_DRIVER_RACE_POINTS: dict[int, int] = {
    1: 25,
    2: 18,
    3: 15,
    4: 12,
    5: 10,
    6: 8,
    7: 6,
    8: 4,
    9: 2,
    10: 1,
}

# Sprint race — top 8 score (8, 7, 6, 5, 4, 3, 2, 1)
_DRIVER_SPRINT_POINTS: dict[int, int] = {
    1: 8,
    2: 7,
    3: 6,
    4: 5,
    5: 4,
    6: 3,
    7: 2,
    8: 1,
}

# Qualifying — positions 1–10 (10 down to 1)
_DRIVER_QUALI_POINTS: dict[int, int] = {
    1: 10,
    2: 9,
    3: 8,
    4: 7,
    5: 6,
    6: 5,
    7: 4,
    8: 3,
    9: 2,
    10: 1,
}

PENALTY_NOT_CLASSIFIED_RACE = -20
PENALTY_NOT_CLASSIFIED_SPRINT = -10

# Approximate 2026 prices (USD millions) — refresh from in-game values when available
DRIVER_PRICES_M: dict[str, float] = {
    "VER": 30.0,
    "NOR": 28.5,
    "LEC": 27.0,
    "PIA": 26.0,
    "SAI": 24.0,
    "HAM": 23.0,
    "RUS": 22.0,
    "PER": 20.0,
    "ALO": 18.0,
    "ALB": 16.0,
    "GAS": 14.0,
    "OCO": 13.0,
    "STR": 12.0,
    "TSU": 11.0,
    "HUL": 10.0,
    "MAG": 9.5,
    "BOT": 9.0,
    "ZHOU": 8.5,
    "LAW": 8.0,
    "SAR": 7.5,
    "BEA": 7.0,
}

CONSTRUCTOR_PRICES_M: dict[str, float] = {
    "RBR": 28.0,
    "MCL": 27.0,
    "FER": 26.0,
    "MER": 24.0,
    "AM": 18.0,
    "ALP": 12.0,
    "WIL": 10.0,
    "RB": 9.0,
    "HAA": 8.0,
    "SAU": 7.5,
    "CAD": 7.0,
}


def _clamp_price(price: float) -> float:
    return max(MIN_ASSET_PRICE_M, price)


def driver_price_m(code: str) -> float:
    """Return driver price in millions (minimum $3M floor)."""
    return _clamp_price(DRIVER_PRICES_M.get(code.upper(), 15.0))


def constructor_price_m(code: str) -> float:
    """Return constructor price in millions (minimum $3M floor)."""
    return _clamp_price(CONSTRUCTOR_PRICES_M.get(code.upper(), 10.0))


def team_value_m(
    driver_codes: list[str],
    constructor_codes: list[str],
) -> float:
    """
    Total squad cost in millions (must not exceed BUDGET_CAP_M).

    Args:
        driver_codes: Up to 5 driver codes.
        constructor_codes: Up to 2 constructor codes.

    Returns:
        Sum of asset prices.
    """
    total = sum(driver_price_m(c) for c in driver_codes)
    total += sum(constructor_price_m(c) for c in constructor_codes)
    return round(total, 2)


def budget_remaining_m(
    driver_codes: list[str],
    constructor_codes: list[str],
) -> float:
    """Budget left after current squad selection."""
    return round(BUDGET_CAP_M - team_value_m(driver_codes, constructor_codes), 2)


def validate_driver_count(driver_codes: list[str]) -> bool:
    """True when exactly five drivers are selected."""
    return len(driver_codes) == DRIVERS_PER_TEAM


def validate_constructor_count(constructor_codes: list[str]) -> bool:
    """True when exactly two constructors are selected."""
    return len(constructor_codes) == CONSTRUCTORS_PER_TEAM


def validate_team_under_budget(
    driver_codes: list[str],
    constructor_codes: list[str],
) -> bool:
    """True when squad fits the $100M cap."""
    return team_value_m(driver_codes, constructor_codes) <= BUDGET_CAP_M


def driver_points_race(finishing_position: int | None, *, classified: bool = True) -> int:
    """
    Official Grand Prix points for a finishing position.

    Args:
        finishing_position: 1–10 for points positions.
        classified: False for DNF/NC → -20 penalty.

    Returns:
        Fantasy points for the race session.
    """
    if not classified or finishing_position is None or finishing_position > 10:
        if finishing_position is None or finishing_position > 20:
            return PENALTY_NOT_CLASSIFIED_RACE
        return 0
    return _DRIVER_RACE_POINTS.get(finishing_position, 0)


def driver_points_sprint(finishing_position: int | None, *, classified: bool = True) -> int:
    """Official Sprint points (2026 DNF/NC = -10)."""
    if not classified or finishing_position is None or finishing_position > 8:
        if finishing_position is None or finishing_position > 20:
            return PENALTY_NOT_CLASSIFIED_SPRINT
        return 0
    return _DRIVER_SPRINT_POINTS.get(finishing_position, 0)


def driver_points_qualifying(grid_position: int | None) -> int:
    """Official qualifying points (P1–P10)."""
    if grid_position is None or grid_position > 10:
        return 0
    return _DRIVER_QUALI_POINTS.get(grid_position, 0)


def constructor_points_race(
    driver_race_points: list[int],
) -> int:
    """
    Constructor race score = sum of both drivers' race points (simplified).

    Pit-stop bonuses and other constructor-only categories are not modeled yet.
    """
    return sum(driver_race_points)


def transfer_penalty_points(transfers_used: int, free_allowance: int) -> int:
    """
    Points deduction for transfers above the free allowance.

    Per official rules: -10 per extra transfer beyond free allowance (max 3 with bank).

    Args:
        transfers_used: Net driver/constructor changes this week.
        free_allowance: 0–3 (2 default, 3 if banked).

    Returns:
        Negative points total (0 if within allowance).
    """
    extra = max(0, transfers_used - free_allowance)
    return -PENALTY_EXTRA_TRANSFER_PTS * extra


def max_affordable_transfers(transfers_available: int, *, limitless_chip: bool = False) -> int:
    """
    Maximum transfers to enumerate for pick generation.

    Args:
        transfers_available: User-stored allowance (0–3, or limitless sentinel).
        limitless_chip: True when Limitless chip active this weekend.

    Returns:
        Cap on transfer count for combinatorics.
    """
    if limitless_chip or transfers_available >= TRANSFERS_LIMITLESS_SENTINEL:
        return DRIVERS_PER_TEAM
    return min(max(0, transfers_available), MAX_TRANSFERS_WITH_BANK)


def normalize_chip_name(raw: str) -> str | None:
    """Map user/DB chip label to canonical 2026 chip id."""
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return _CHIP_ALIASES.get(key)

def chip_available(chips_used: dict[str, bool] | dict, chip: str) -> bool:
    """True if chip has not been used this season."""
    canonical = normalize_chip_name(chip) or chip
    return not chips_used.get(canonical, False)
