"""Driver number ↔ code mapping for OpenF1 data."""

from __future__ import annotations

# FIA 2026 grid (fallback when session /drivers roster is unavailable).
# Source: FIA 2026 entry list / formula1.com driver numbers.
_DRIVER_NUMBER_TO_CODE_2026: dict[int, str] = {
    1: "NOR",
    3: "VER",
    5: "BOR",
    6: "HAD",
    10: "GAS",
    11: "PER",
    12: "ANT",
    14: "ALO",
    16: "LEC",
    18: "STR",
    23: "ALB",
    27: "HUL",
    30: "LAW",
    31: "OCO",
    41: "LIN",
    43: "COL",
    44: "HAM",
    55: "SAI",
    63: "RUS",
    77: "BOT",
    81: "PIA",
    87: "BEA",
}

# Legacy numbers for pre-2026 OpenF1 sessions (same driver number, different holder).
_DRIVER_NUMBER_TO_CODE_LEGACY: dict[int, str] = {
    1: "VER",
    4: "NOR",
    10: "GAS",
    11: "PER",
    14: "ALO",
    16: "LEC",
    18: "STR",
    20: "MAG",
    22: "TSU",
    23: "ALB",
    24: "ZHOU",
    27: "HUL",
    31: "OCO",
    44: "HAM",
    55: "SAI",
    63: "RUS",
    77: "BOT",
    81: "PIA",
}

_DRIVER_NUMBER_TO_CODE: dict[int, str] = {
    **_DRIVER_NUMBER_TO_CODE_LEGACY,
    **_DRIVER_NUMBER_TO_CODE_2026,
}


def driver_code_for(driver_number: int) -> str:
    """
    Map OpenF1 driver_number to three-letter code (static fallback).

    Prefer session roster from OpenF1 GET /v1/drivers when building race aggregates.

    Args:
        driver_number: OpenF1 driver number.

    Returns:
        Driver code or UNK{n} placeholder.
    """
    return _DRIVER_NUMBER_TO_CODE.get(driver_number, f"UNK{driver_number}")


def team_for_driver(driver_code: str) -> str:
    """Return a display team name for a driver code."""
    teams: dict[str, str] = {
        "VER": "Red Bull Racing",
        "HAD": "Red Bull Racing",
        "PER": "Cadillac",
        "NOR": "McLaren",
        "PIA": "McLaren",
        "LEC": "Ferrari",
        "HAM": "Ferrari",
        "SAI": "Williams",
        "RUS": "Mercedes",
        "ANT": "Mercedes",
        "ALO": "Aston Martin",
        "STR": "Aston Martin",
        "GAS": "Alpine",
        "COL": "Alpine",
        "OCO": "Haas",
        "BEA": "Haas",
        "ALB": "Williams",
        "LAW": "Racing Bulls",
        "LIN": "Racing Bulls",
        "HUL": "Audi",
        "BOR": "Audi",
        "BOT": "Cadillac",
        # Legacy codes still referenced in historical data / prices
        "MAG": "Haas",
        "TSU": "Racing Bulls",
        "ZHOU": "Kick Sauber",
        "SAR": "Williams",
    }
    return teams.get(driver_code.upper(), "Unknown")


def constructor_code_for_driver(driver_code: str) -> str:
    """Return fantasy constructor code (e.g. FER, RBR) for driver code."""
    mapping: dict[str, str] = {
        "VER": "RBR",
        "HAD": "RBR",
        "PER": "CAD",
        "NOR": "MCL",
        "PIA": "MCL",
        "LEC": "FER",
        "HAM": "FER",
        "SAI": "WIL",
        "RUS": "MER",
        "ANT": "MER",
        "ALO": "AMR",
        "STR": "AMR",
        "GAS": "VCA",
        "COL": "VCA",
        "OCO": "HAA",
        "BEA": "HAA",
        "ALB": "WIL",
        "LAW": "RBT",
        "LIN": "RBT",
        "HUL": "SAU",
        "BOR": "SAU",
        "BOT": "CAD",
        # Legacy aliases (historical picks / prices)
        "MAG": "HAA",
        "TSU": "RBT",
        "ZHOU": "SAU",
        "SAR": "WIL",
    }
    return mapping.get(driver_code.upper(), "UNK")
