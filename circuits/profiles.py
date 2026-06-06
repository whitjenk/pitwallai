"""
Circuit profiles for the 2026 F1 calendar.

Metrics are grounded in long-run historical behaviour (2018–2025): Monaco ranks
among the lowest overtaking circuits; Monza among the highest; street circuits
show higher safety-car rates and lower positions-gained ceilings. Values are
static strategist priors — not runtime API fetches.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CircuitProfile(BaseModel):
    """
    Fantasy-relevant circuit characteristics.

    Attributes:
        circuit_key: Stable OpenF1-aligned identifier (snake_case).
        display_name: Human-readable circuit name.
        overtaking_difficulty: 0–1 (1 = nearly impossible).
        tire_deg_rate: 0–1 strategy variance from tire wear.
        weather_sensitivity: 0–1 impact of rain on race outcome.
        safety_car_probability: Historical SC/VSC likelihood per race.
        positions_gained_ceiling: Realistic max positions gained in a race.
        sector_characteristics: Tags for setup and tyre behaviour.
        notes: Plain-English strategist summary.
        openf1_circuit_name: circuit_short_name for OpenF1 session lookup.
    """

    model_config = ConfigDict(frozen=True)

    circuit_key: str
    display_name: str
    overtaking_difficulty: float = Field(ge=0.0, le=1.0)
    tire_deg_rate: float = Field(ge=0.0, le=1.0)
    weather_sensitivity: float = Field(ge=0.0, le=1.0)
    safety_car_probability: float = Field(ge=0.0, le=1.0)
    positions_gained_ceiling: int = Field(ge=0, le=20)
    sector_characteristics: list[str]
    notes: str
    openf1_circuit_name: str


# 2026 calendar — 24 Grands Prix
_CIRCUITS: tuple[CircuitProfile, ...] = (
    CircuitProfile(
        circuit_key="bahrain",
        display_name="Bahrain International Circuit",
        overtaking_difficulty=0.42,
        tire_deg_rate=0.72,
        weather_sensitivity=0.12,
        safety_car_probability=0.28,
        positions_gained_ceiling=8,
        sector_characteristics=["medium_downforce", "abrasive_surface", "night_race"],
        notes="High rear tyre deg on abrasive asphalt; undercut strong. Limited weather risk.",
        openf1_circuit_name="Sakhir",
    ),
    CircuitProfile(
        circuit_key="jeddah",
        display_name="Jeddah Corniche Circuit",
        overtaking_difficulty=0.38,
        tire_deg_rate=0.58,
        weather_sensitivity=0.10,
        safety_car_probability=0.35,
        positions_gained_ceiling=9,
        sector_characteristics=["street_circuit", "high_speed", "wall_penalty"],
        notes="Long straights aid passes but walls punish mistakes; SC clusters common.",
        openf1_circuit_name="Jeddah",
    ),
    CircuitProfile(
        circuit_key="melbourne",
        display_name="Albert Park",
        overtaking_difficulty=0.48,
        tire_deg_rate=0.55,
        weather_sensitivity=0.38,
        safety_car_probability=0.32,
        positions_gained_ceiling=7,
        sector_characteristics=["street_circuit", "medium_downforce", "variable_grip"],
        notes="Season opener often mixed conditions; tyre graining if track evolution slow.",
        openf1_circuit_name="Melbourne",
    ),
    CircuitProfile(
        circuit_key="suzuka",
        display_name="Suzuka International Racing Course",
        overtaking_difficulty=0.52,
        tire_deg_rate=0.68,
        weather_sensitivity=0.42,
        safety_car_probability=0.22,
        positions_gained_ceiling=6,
        sector_characteristics=["high_downforce", "sequential_corners", "tyre_limited"],
        notes="Rhythm circuit — follow closely hurts tyres; rain transforms strategy.",
        openf1_circuit_name="Suzuka",
    ),
    CircuitProfile(
        circuit_key="shanghai",
        display_name="Shanghai International Circuit",
        overtaking_difficulty=0.35,
        tire_deg_rate=0.50,
        weather_sensitivity=0.30,
        safety_car_probability=0.25,
        positions_gained_ceiling=9,
        sector_characteristics=["long_straight", "medium_downforce"],
        notes="Main straight enables DRS trains; manageable deg on newer asphalt.",
        openf1_circuit_name="Shanghai",
    ),
    CircuitProfile(
        circuit_key="miami",
        display_name="Miami International Autodrome",
        overtaking_difficulty=0.45,
        tire_deg_rate=0.62,
        weather_sensitivity=0.22,
        safety_car_probability=0.30,
        positions_gained_ceiling=7,
        sector_characteristics=["street_circuit", "bumpy", "medium_downforce"],
        notes="Bumpy surface drives overheating; passing possible on harbour straight.",
        openf1_circuit_name="Miami",
    ),
    CircuitProfile(
        circuit_key="imola",
        display_name="Autodromo Enzo e Dino Ferrari",
        overtaking_difficulty=0.58,
        tire_deg_rate=0.60,
        weather_sensitivity=0.28,
        safety_car_probability=0.26,
        positions_gained_ceiling=6,
        sector_characteristics=["narrow", "historic", "medium_downforce"],
        notes="Tricky passing at Tosa/Variante Alta; strategy often track-position locked.",
        openf1_circuit_name="Imola",
    ),
    CircuitProfile(
        circuit_key="monaco",
        display_name="Circuit de Monaco",
        overtaking_difficulty=0.95,
        tire_deg_rate=0.52,
        weather_sensitivity=0.40,
        safety_car_probability=0.42,
        positions_gained_ceiling=2,
        sector_characteristics=["street_circuit", "low_speed", "qualifying_critical"],
        notes="Qualifying IS the race; SC lottery only real overtaking catalyst.",
        # OpenF1 labels this circuit "Monte Carlo" (not "Monaco").
        openf1_circuit_name="Monte Carlo",
    ),
    CircuitProfile(
        circuit_key="barcelona",
        display_name="Circuit de Barcelona-Catalunya",
        overtaking_difficulty=0.55,
        tire_deg_rate=0.75,
        weather_sensitivity=0.18,
        safety_car_probability=0.20,
        positions_gained_ceiling=6,
        sector_characteristics=["high_downforce", "front_limited", "wind_sensitive"],
        notes="Historically extreme front-left deg; testing baseline circuit.",
        # OpenF1 labels this circuit "Catalunya" (not "Barcelona").
        openf1_circuit_name="Catalunya",
    ),
    CircuitProfile(
        circuit_key="montreal",
        display_name="Circuit Gilles Villeneuve",
        overtaking_difficulty=0.32,
        tire_deg_rate=0.48,
        weather_sensitivity=0.35,
        safety_car_probability=0.38,
        positions_gained_ceiling=10,
        sector_characteristics=["low_downforce", "chicanes", "wall_of_champions"],
        notes="Low drag + heavy braking zones = passes; SC and walls reshape order.",
        openf1_circuit_name="Montreal",
    ),
    CircuitProfile(
        circuit_key="spielberg",
        display_name="Red Bull Ring",
        overtaking_difficulty=0.28,
        tire_deg_rate=0.45,
        weather_sensitivity=0.32,
        safety_car_probability=0.24,
        positions_gained_ceiling=10,
        sector_characteristics=["short_lap", "elevation", "low_downforce"],
        notes="Short lap, big DRS effect; rain showers possible in Styrian hills.",
        openf1_circuit_name="Spielberg",
    ),
    CircuitProfile(
        circuit_key="silverstone",
        display_name="Silverstone Circuit",
        overtaking_difficulty=0.40,
        tire_deg_rate=0.58,
        weather_sensitivity=0.45,
        safety_car_probability=0.22,
        positions_gained_ceiling=8,
        sector_characteristics=["high_speed", "lateral_load", "wind_sensitive"],
        notes="Copse/Maggotts sequence; weather lottery famous — inters can win.",
        openf1_circuit_name="Silverstone",
    ),
    CircuitProfile(
        circuit_key="spa",
        display_name="Circuit de Spa-Francorchamps",
        overtaking_difficulty=0.30,
        tire_deg_rate=0.52,
        weather_sensitivity=0.55,
        safety_car_probability=0.30,
        positions_gained_ceiling=11,
        sector_characteristics=["long_straight", "high_speed", "microclimate"],
        notes="Eau Rouge sector; rain on one sector only — fantasy chaos circuit.",
        openf1_circuit_name="Spa-Francorchamps",
    ),
    CircuitProfile(
        circuit_key="hungaroring",
        display_name="Hungaroring",
        overtaking_difficulty=0.78,
        tire_deg_rate=0.70,
        weather_sensitivity=0.25,
        safety_car_probability=0.28,
        positions_gained_ceiling=5,
        sector_characteristics=["narrow", "dirty_air", "high_downforce"],
        notes="Difficult to follow — undercut paradise; track position paramount.",
        openf1_circuit_name="Hungaroring",
    ),
    CircuitProfile(
        circuit_key="zandvoort",
        display_name="Circuit Zandvoort",
        overtaking_difficulty=0.72,
        tire_deg_rate=0.55,
        weather_sensitivity=0.30,
        safety_car_probability=0.22,
        positions_gained_ceiling=5,
        sector_characteristics=["banked", "medium_downforce", "dirty_air"],
        notes="Banked T14 not enough for easy passes; quali track position critical.",
        openf1_circuit_name="Zandvoort",
    ),
    CircuitProfile(
        circuit_key="monza",
        display_name="Autodromo Nazionale Monza",
        overtaking_difficulty=0.22,
        tire_deg_rate=0.38,
        weather_sensitivity=0.20,
        safety_car_probability=0.20,
        positions_gained_ceiling=12,
        sector_characteristics=["low_downforce", "slipstream", "low_deg"],
        notes="Temple of speed — lowest downforce; DRS trains and big position swings.",
        openf1_circuit_name="Monza",
    ),
    CircuitProfile(
        circuit_key="baku",
        display_name="Baku City Circuit",
        overtaking_difficulty=0.36,
        tire_deg_rate=0.50,
        weather_sensitivity=0.18,
        safety_car_probability=0.40,
        positions_gained_ceiling=10,
        sector_characteristics=["street_circuit", "long_straight", "wall_risk"],
        notes="Castle section vs 2km straight dichotomy; SC and penalties shuffle order.",
        openf1_circuit_name="Baku",
    ),
    CircuitProfile(
        circuit_key="marina_bay",
        display_name="Marina Bay Street Circuit",
        overtaking_difficulty=0.82,
        tire_deg_rate=0.65,
        weather_sensitivity=0.35,
        safety_car_probability=0.45,
        positions_gained_ceiling=4,
        sector_characteristics=["street_circuit", "high_downforce", "humidity"],
        notes="Night race heat management; SC-heavy — quali position dominates.",
        openf1_circuit_name="Singapore",
    ),
    CircuitProfile(
        circuit_key="austin",
        display_name="Circuit of the Americas",
        overtaking_difficulty=0.44,
        tire_deg_rate=0.62,
        weather_sensitivity=0.28,
        safety_car_probability=0.24,
        positions_gained_ceiling=8,
        sector_characteristics=["elevation", "mixed", "medium_downforce"],
        notes="S1 esses vs long back straight; tyre deg in S1 often sets strategy.",
        openf1_circuit_name="Austin",
    ),
    CircuitProfile(
        circuit_key="mexico_city",
        display_name="Autódromo Hermanos Rodríguez",
        overtaking_difficulty=0.50,
        tire_deg_rate=0.58,
        weather_sensitivity=0.15,
        safety_car_probability=0.22,
        positions_gained_ceiling=7,
        sector_characteristics=["thin_air", "medium_downforce", "stadium_section"],
        notes="Altitude reduces drag effect; tyre overheating in stadium section.",
        openf1_circuit_name="Mexico City",
    ),
    CircuitProfile(
        circuit_key="interlagos",
        display_name="Autódromo José Carlos Pace",
        overtaking_difficulty=0.34,
        tire_deg_rate=0.68,
        weather_sensitivity=0.48,
        safety_car_probability=0.30,
        positions_gained_ceiling=10,
        sector_characteristics=["elevation", "short_lap", "weather_lottery"],
        notes="Anti-clockwise + altitude; rain common — high fantasy variance.",
        openf1_circuit_name="Interlagos",
    ),
    CircuitProfile(
        circuit_key="las_vegas",
        display_name="Las Vegas Strip Circuit",
        overtaking_difficulty=0.46,
        tire_deg_rate=0.55,
        weather_sensitivity=0.12,
        safety_car_probability=0.32,
        positions_gained_ceiling=8,
        sector_characteristics=["street_circuit", "low_grip", "cold_track"],
        notes="Cold night track — tyre warmup critical; straight-line passes possible.",
        openf1_circuit_name="Las Vegas",
    ),
    CircuitProfile(
        circuit_key="lusail",
        display_name="Lusail International Circuit",
        overtaking_difficulty=0.40,
        tire_deg_rate=0.60,
        weather_sensitivity=0.10,
        safety_car_probability=0.26,
        positions_gained_ceiling=8,
        sector_characteristics=["medium_downforce", "wide", "night_race"],
        notes="Wide layout aids passing; tyre thermal management in desert heat.",
        openf1_circuit_name="Lusail",
    ),
    CircuitProfile(
        circuit_key="yas_marina",
        display_name="Yas Marina Circuit",
        overtaking_difficulty=0.52,
        tire_deg_rate=0.58,
        weather_sensitivity=0.08,
        safety_car_probability=0.28,
        positions_gained_ceiling=7,
        sector_characteristics=["medium_downforce", "twilight", "season_finale"],
        notes="Season finale often processional unless strategy undercut; low rain risk.",
        openf1_circuit_name="Yas Marina Circuit",
    ),
)

_REGISTRY: dict[str, CircuitProfile] = {c.circuit_key: c for c in _CIRCUITS}
_BY_OPENF1: dict[str, CircuitProfile] = {c.openf1_circuit_name.lower(): c for c in _CIRCUITS}


def load_circuit_profiles() -> dict[str, CircuitProfile]:
    """
    Load all circuit profiles for injection at startup.

    Returns:
        Map of circuit_key → CircuitProfile (frozen copies).
    """
    return dict(_REGISTRY)


def all_circuit_keys() -> list[str]:
    """All registered circuit_key values for seeding loops."""
    return list(_REGISTRY.keys())


def get_circuit_profile(circuit_key: str) -> CircuitProfile | None:
    """
    Resolve a profile by circuit_key or OpenF1 circuit_short_name.

    Args:
        circuit_key: Internal key or OpenF1 short name.

    Returns:
        CircuitProfile or None.
    """
    key = circuit_key.strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key]
    return _BY_OPENF1.get(circuit_key.strip().lower())
