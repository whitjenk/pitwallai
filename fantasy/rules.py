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

# Onboarding default — user has not entered free transfers yet
TRANSFERS_UNSET = -1

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
PENALTY_QUALIFYING_NC = -5  # NC / DSQ / no time set (official qualifying)
PENALTY_CONSTRUCTOR_DRIVER_DSQ = -20  # Per disqualified driver (constructor race/quali)

# Constructor pit-stop race points (fastest stop of the team's two drivers)
PIT_STOP_WORLD_RECORD_S = 1.8  # Published record (McLaren, 2023 Qatar)
PIT_STOP_FASTEST_BONUS = 5
PIT_STOP_WORLD_RECORD_BONUS = 15

# Approximate prices (USD millions) — edit fantasy/prices.json each race weekend;
# set PITWALL_PRICES_VERIFIED=1 after matching in-game values.
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
    "HAD": 11.0,
    "HUL": 10.0,
    "LAW": 9.5,
    "BOT": 9.0,
    "BEA": 8.5,
    "BOR": 8.0,
    "ANT": 7.5,
    "LIN": 7.0,
    "COL": 6.5,
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
    from fantasy.price_catalog import driver_price_m as _catalog

    return _catalog(code)


def constructor_price_m(code: str) -> float:
    """Return constructor price in millions (minimum $3M floor)."""
    from fantasy.price_catalog import constructor_price_m as _catalog

    return _catalog(code)


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
    Official Grand Prix **finishing-position** points (P1–P10 scale).

    Full F1 Fantasy race scoring also awards positions gained/lost, overtakes,
    fastest lap, and Driver of the Day — not modeled here. PitWallAI pick scoring
    uses this position scale only (see intelligence/recap_metrics.PICK_SCORING_SCOPE).

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


def driver_points_qualifying(grid_position: int | None, *, classified: bool = True) -> int:
    """
    Official qualifying points (P1–P10).

    NC / DSQ / no time set = -5 per published F1 Fantasy rules.
    """
    if not classified or grid_position is None:
        return PENALTY_QUALIFYING_NC
    if grid_position > 10:
        return 0
    return _DRIVER_QUALI_POINTS.get(grid_position, 0)


def constructor_qualifying_progression(
    drivers_in_q2: int,
    drivers_in_q3: int,
) -> int:
    """
    Official constructor qualifying progression bonus (0–2 drivers each phase).

    Neither Q2: -1 · one Q2: +1 · both Q2: +3 · one Q3: +5 · both Q3: +10
    """
    q2 = max(0, min(2, drivers_in_q2))
    q3 = max(0, min(2, drivers_in_q3))
    if q3 == 2:
        return 10
    if q3 == 1:
        return 5
    if q2 == 2:
        return 3
    if q2 == 1:
        return 1
    return -1


def qualifying_phase_counts_from_grid(
    grid_positions: list[int | None],
    *,
    classified: list[bool] | None = None,
) -> tuple[int, int]:
    """
    Estimate Q2/Q3 reach from final qualifying positions (when session flags unavailable).

    P1–10 → reached Q3 (and Q2); P11–15 → reached Q2 only; P16+ / NC → neither.
    """
    drivers_in_q2 = 0
    drivers_in_q3 = 0
    for idx, pos in enumerate(grid_positions[:2]):
        ok = True
        if classified is not None and idx < len(classified):
            ok = classified[idx]
        if not ok or pos is None:
            continue
        if pos <= 10:
            drivers_in_q3 += 1
            drivers_in_q2 += 1
        elif pos <= 15:
            drivers_in_q2 += 1
    return drivers_in_q2, drivers_in_q3


def constructor_points_qualifying(
    driver_quali_points: list[int],
    *,
    drivers_in_q2: int,
    drivers_in_q3: int,
) -> int:
    """Constructor qualifying = sum of drivers' quali pts + Q2/Q3 progression bonus."""
    driver_total = sum(driver_quali_points[:2])
    return driver_total + constructor_qualifying_progression(drivers_in_q2, drivers_in_q3)


def constructor_pit_stop_points(pit_stop_duration_s: float | None) -> int:
    """
    Constructor race pit-stop points from team's fastest stop duration (seconds).

    Official bands: >3.0s=0 · 2.50–2.99=2 · 2.20–2.49=5 · 2.00–2.19=10 · <2.0=20
    """
    if pit_stop_duration_s is None:
        return 0
    duration = float(pit_stop_duration_s)
    if duration >= 3.0:
        return 0
    if duration >= 2.5:
        return 2
    if duration >= 2.2:
        return 5
    if duration >= 2.0:
        return 10
    return 20


def constructor_points_race(
    driver_race_points: list[int],
    *,
    pit_stop_duration_s: float | None = None,
    has_fastest_pit_in_race: bool = False,
    pit_world_record: bool = False,
    drivers_dsq: int = 0,
) -> int:
    """
    Official constructor Grand Prix score.

    Sum of both drivers' race points (excludes Driver of the Day), plus pit-stop
    time tier, fastest-pit bonus (+5), world-record bonus (+15), minus -20 per DSQ driver.
    """
    total = sum(driver_race_points[:2])
    total += constructor_pit_stop_points(pit_stop_duration_s)
    if pit_world_record and pit_stop_duration_s is not None and pit_stop_duration_s <= PIT_STOP_WORLD_RECORD_S:
        total += PIT_STOP_WORLD_RECORD_BONUS
    elif has_fastest_pit_in_race:
        total += PIT_STOP_FASTEST_BONUS
    total += PENALTY_CONSTRUCTOR_DRIVER_DSQ * max(0, min(2, drivers_dsq))
    return total


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


def transfers_configured(transfers_available: int) -> bool:
    """True when the user has completed the transfers onboarding step."""
    return transfers_available >= 0


def max_affordable_transfers(transfers_available: int, *, limitless_chip: bool = False) -> int:
    """
    Maximum transfers to enumerate for pick generation.

    Args:
        transfers_available: User-stored allowance (0–3, or limitless sentinel).
        limitless_chip: True when Limitless chip active this weekend.

    Returns:
        Cap on transfer count for combinatorics.
    """
    if not transfers_configured(transfers_available):
        return 0
    if limitless_chip:
        return DRIVERS_PER_TEAM
    return min(transfers_available, MAX_TRANSFERS_WITH_BANK)


def free_transfer_allowance(transfers_available: int, *, limitless_chip: bool = False) -> int:
    """
    Free transfers before -10 pt penalties apply (0–3, or uncapped with Limitless).

    Separate from max_affordable_transfers(), which caps combinatorial search depth.
    """
    if not transfers_configured(transfers_available):
        return 0
    if limitless_chip:
        return DRIVERS_PER_TEAM
    return min(transfers_available, MAX_TRANSFERS_WITH_BANK)


def validate_driver_codes(driver_codes: list[str]) -> str | None:
    """
    Validate a five-driver squad for onboarding.

    Returns:
        Error message, or None when valid.
    """
    codes = [c.strip().upper() for c in driver_codes]
    if len(codes) != DRIVERS_PER_TEAM:
        return f"Need exactly {DRIVERS_PER_TEAM} drivers."
    if len(set(codes)) != len(codes):
        return "Driver codes must be unique."
    unknown = [c for c in codes if c not in DRIVER_PRICES_M]
    if unknown:
        return f"Unknown driver code(s): {', '.join(unknown)}."
    return None


def validate_constructor_codes(constructor_codes: list[str]) -> str | None:
    """Validate two constructor codes. Returns error message or None."""
    codes = [c.strip().upper() for c in constructor_codes]
    if len(codes) != CONSTRUCTORS_PER_TEAM:
        return f"Need exactly {CONSTRUCTORS_PER_TEAM} constructors."
    if len(set(codes)) != len(codes):
        return "Constructor codes must be unique."
    unknown = [c for c in codes if c not in CONSTRUCTOR_PRICES_M]
    if unknown:
        return f"Unknown constructor code(s): {', '.join(unknown)}."
    return None


def normalize_chip_name(raw: str) -> str | None:
    """Map user/DB chip label to canonical 2026 chip id."""
    key = raw.strip().lower().replace(" ", "_").replace("-", "_")
    return _CHIP_ALIASES.get(key)


def chip_available(chips_used: dict[str, bool] | dict, chip: str) -> bool:
    """True if chip has not been used this season."""
    canonical = normalize_chip_name(chip) or chip
    return not chips_used.get(canonical, False)
