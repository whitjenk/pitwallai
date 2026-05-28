"""Driver number ↔ code mapping for OpenF1 data."""

from __future__ import annotations

# 2025 grid baseline — extend as seasons change.
_DRIVER_NUMBER_TO_CODE: dict[int, str] = {
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
    81: "PIA",
    77: "BOT",
}


def driver_code_for(driver_number: int) -> str:
    """
    Map OpenF1 driver_number to three-letter code.

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
        "PER": "Red Bull Racing",
        "NOR": "McLaren",
        "PIA": "McLaren",
        "LEC": "Ferrari",
        "SAI": "Ferrari",
        "HAM": "Mercedes",
        "RUS": "Mercedes",
        "ALO": "Aston Martin",
        "STR": "Aston Martin",
        "GAS": "Alpine",
        "OCO": "Alpine",
        "ALB": "Williams",
        "SAR": "Williams",
        "TSU": "RB",
        "LAW": "RB",
        "HUL": "Haas",
        "MAG": "Haas",
        "BOT": "Kick Sauber",
        "ZHOU": "Kick Sauber",
    }
    return teams.get(driver_code.upper(), "Unknown")
