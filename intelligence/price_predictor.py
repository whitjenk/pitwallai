"""One-race-ahead driver price direction predictor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from fantasy.rules import DRIVER_PRICES_M
from intelligence.drivers import driver_code_for
from intelligence.price_history import get_price_history
from intelligence.repository import (
    load_latest_pick_ownership,
    load_practice_signals_by_circuit,
    upsert_price_predictions,
)
from openf1.client import OpenF1Client


class PricePredictionOut(BaseModel):
    """Return payload for price predictions."""

    model_config = ConfigDict(frozen=True)

    driver_code: str
    race_key: str
    predicted_direction: str
    predicted_magnitude: float
    confidence: float
    reasoning: str
    signal_breakdown: dict[str, Any]
    price_threshold_note: str | None = None


def _avg_points_on_price_move(hist: list, *, rising: bool) -> float:
    pts: list[float] = []
    for row in hist:
        if row.price_change is None or row.fantasy_points_scored is None:
            continue
        if rising and row.price_change >= 0.1:
            pts.append(float(row.fantasy_points_scored))
        if not rising and row.price_change <= -0.1:
            pts.append(float(row.fantasy_points_scored))
    return sum(pts) / len(pts) if pts else 12.0


def _price_threshold_fields(
    *,
    practice_align: float,
    circuit_hist: float,
    confidence: float,
    hist: list,
) -> tuple[str | None, dict[str, Any]]:
    """Threshold note + breakdown when confidence > 0.6."""
    rise_pts = _avg_points_on_price_move(hist, rising=True)
    fall_pts = _avg_points_on_price_move(hist, rising=False)
    pace_pts = max(0.0, practice_align * 15.0 + circuit_hist * 12.0 + 8.0)
    gap = pace_pts - rise_pts
    note: str | None = None
    snippet: str | None = None
    if confidence > 0.6:
        if gap > 0:
            note = "On pace for price rise — holding looks smart"
        elif gap < -5:
            note = "Below rise threshold — price drop risk if underperforms"
        else:
            note = "Close to price threshold — borderline hold/sell"
        snippet = f"needs {rise_pts:.0f}pts for rise, on {pace_pts:.0f}pt pace"
    return note, {
        "points_needed_for_rise": round(rise_pts, 1),
        "points_needed_for_fall": round(fall_pts, 1),
        "current_pace_pts": round(pace_pts, 1),
        "threshold_gap": round(gap, 1),
        "snippet": snippet,
    }


def _norm(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    lo = min(values.values())
    hi = max(values.values())
    if hi - lo < 1e-9:
        return {k: 0.0 for k in values}
    return {k: (2.0 * ((v - lo) / (hi - lo)) - 1.0) for k, v in values.items()}


def _direction(score: float) -> str:
    if score > 0.25:
        return "UP"
    if score < -0.25:
        return "DOWN"
    return "STABLE"


def _magnitude(score: float) -> float:
    return round(min(0.5, abs(score) * 0.6) * 10.0) / 10.0


async def _momentum_signal(codes: list[str]) -> dict[str, float]:
    raw: dict[str, float] = {}
    for code in codes:
        hist = await get_price_history(code, last_n_races=3)
        pts = [float(r.fantasy_points_scored or 0.0) for r in hist[-3:]]
        if len(pts) < 3:
            pts = ([0.0] * (3 - len(pts))) + pts
        raw[code] = pts[-1] * 0.5 + pts[-2] * 0.3 + pts[-3] * 0.2
    return _norm(raw)


async def _value_ratio_signal(codes: list[str], current_prices: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for code in codes:
        hist = await get_price_history(code, last_n_races=12)
        if not hist:
            out[code] = 0.0
            continue
        season_vals = [
            (float(h.fantasy_points_scored or 0.0) / max(1.0, float(h.price)))
            for h in hist
        ]
        season_avg = sum(season_vals) / len(season_vals) if season_vals else 0.0
        current = season_vals[-1] if season_vals else 0.0
        if season_avg <= 1e-9:
            out[code] = 0.0
            continue
        delta = (current - season_avg) / season_avg
        if delta > 0.2:
            out[code] = min(1.0, delta)
        elif delta < -0.2:
            out[code] = max(-1.0, delta)
        else:
            out[code] = 0.0
    return out


async def _circuit_signal(codes: list[str], circuit_key: str) -> dict[str, float]:
    out = {code: 0.0 for code in codes}
    client = OpenF1Client()
    # best-effort: use last 3 race results at this circuit.
    by_code: dict[str, list[float]] = {code: [] for code in codes}
    for year in (2025, 2024, 2023):
        sk = await client.find_session_key(year=year, circuit_short_name=circuit_key, session_name="Race")
        if not sk:
            continue
        rows = await client.get_session_results(sk)
        for row in rows:
            if row.position is None:
                continue
            code = driver_code_for(row.driver_number)
            if code in by_code:
                by_code[code].append(float(max(0, 26 - row.position)))
    for code in codes:
        hist = await get_price_history(code, last_n_races=12)
        season_points = [float(h.fantasy_points_scored or 0.0) for h in hist]
        season_avg = (sum(season_points) / len(season_points)) if season_points else 0.0
        if not by_code[code] or season_avg <= 1e-9:
            out[code] = 0.0
            continue
        circ_avg = sum(by_code[code][:3]) / len(by_code[code][:3])
        ratio = circ_avg / season_avg
        if ratio > 1.15:
            out[code] = 0.3
        elif ratio < 0.85:
            out[code] = -0.3
        else:
            out[code] = 0.0
    return out


async def _practice_signal(codes: list[str], circuit_key: str) -> tuple[dict[str, float], bool]:
    out = {code: 0.0 for code in codes}
    rows = await load_practice_signals_by_circuit(circuit_key)
    if not rows:
        return out, False
    latest_by_driver: dict[str, Any] = {}
    for row in rows:
        latest_by_driver[row.driver_code] = row
    for code in codes:
        r = latest_by_driver.get(code)
        if not r:
            continue
        if (r.setup_sentiment or 0.0) > 0.6 and not (r.anomaly_flags or []):
            out[code] = 0.2
        elif r.anomaly_flags:
            out[code] = -0.2
    return out, True


async def _ownership_signal(codes: list[str], race_key: str) -> dict[str, float]:
    out = {code: 0.0 for code in codes}
    rows = await load_latest_pick_ownership(race_key)
    for code in codes:
        row = rows.get(code)
        if row is None:
            continue
        pct = float(row.pitwallai_ownership_pct)
        if pct > 50.0:
            out[code] = 0.2
        elif pct < 20.0:
            out[code] = -0.05
    return out


async def predict_price_changes(race_key: str, circuit_key: str) -> list[PricePredictionOut]:
    """
    Predict next-race price direction for all drivers.
    """
    codes = list(DRIVER_PRICES_M.keys())
    current_prices = {}
    for code in codes:
        hist = await get_price_history(code, last_n_races=1)
        current_prices[code] = float(hist[-1].price) if hist else float(DRIVER_PRICES_M.get(code, 10.0))

    s1 = await _momentum_signal(codes)
    s2 = await _value_ratio_signal(codes, current_prices)
    s3 = await _circuit_signal(codes, circuit_key)
    s4, has_practice = await _practice_signal(codes, circuit_key)
    s5 = await _ownership_signal(codes, race_key)

    weights = {
        "momentum": 0.30,
        "value_ratio": 0.25,
        "circuit_hist": 0.20,
        "practice_align": 0.15,
        "ownership_pressure": 0.10,
    }
    if not has_practice:
        # redistribute practice weight over predictive priors.
        weights["momentum"] += 0.08
        weights["value_ratio"] += 0.04
        weights["circuit_hist"] += 0.03
        weights["practice_align"] = 0.0

    rows: list[PricePredictionOut] = []
    upserts: list[dict[str, Any]] = []
    for code in codes:
        contrib = {
            "momentum": s1.get(code, 0.0) * weights["momentum"],
            "value_ratio": s2.get(code, 0.0) * weights["value_ratio"],
            "circuit_hist": s3.get(code, 0.0) * weights["circuit_hist"],
            "practice_align": s4.get(code, 0.0) * weights["practice_align"],
            "ownership_pressure": s5.get(code, 0.0) * weights["ownership_pressure"],
        }
        raw_score = max(-1.0, min(1.0, sum(contrib.values())))
        direction = _direction(raw_score)
        mag = _magnitude(raw_score)

        aligned = [v for v in (s1.get(code, 0.0), s2.get(code, 0.0), s3.get(code, 0.0), s4.get(code, 0.0), s5.get(code, 0.0)) if abs(v) > 0.05]
        pos = sum(1 for v in aligned if v > 0)
        neg = sum(1 for v in aligned if v < 0)
        conf = 0.5
        if aligned and (pos == 0 or neg == 0):
            conf += 0.1
        if abs(s1.get(code, 0.0)) > 0.7:
            conf += 0.1
        if abs(s3.get(code, 0.0)) > 0.0:
            conf += 0.1
        if pos > 0 and neg > 0:
            conf -= 0.1
        hist = await get_price_history(code, last_n_races=10)
        if len(hist) < 5:
            conf -= 0.1
        conf = max(0.0, min(0.9, conf))
        threshold_note, threshold_meta = _price_threshold_fields(
            practice_align=s4.get(code, 0.0),
            circuit_hist=s3.get(code, 0.0),
            confidence=conf,
            hist=hist,
        )

        breakdown = {
            "momentum": {"score": round(s1.get(code, 0.0), 3), "weight": weights["momentum"], "contribution": round(contrib["momentum"], 3)},
            "value_ratio": {"score": round(s2.get(code, 0.0), 3), "weight": weights["value_ratio"], "contribution": round(contrib["value_ratio"], 3)},
            "circuit_hist": {"score": round(s3.get(code, 0.0), 3), "weight": weights["circuit_hist"], "contribution": round(contrib["circuit_hist"], 3)},
            "practice_align": {"score": round(s4.get(code, 0.0), 3), "weight": weights["practice_align"], "contribution": round(contrib["practice_align"], 3)},
            "ownership_pressure": {"score": round(s5.get(code, 0.0), 3), "weight": weights["ownership_pressure"], "contribution": round(contrib["ownership_pressure"], 3)},
            "combined": round(raw_score, 3),
            "direction": direction,
            "magnitude": mag,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "threshold": threshold_meta,
        }
        dir_label = "up" if direction == "UP" else "down" if direction == "DOWN" else "stable"
        reasoning = (
            f"In-game price predicted {dir_label} from momentum {s1.get(code,0.0):+.2f}, "
            f"value trend {s2.get(code,0.0):+.2f}, and circuit bias {s3.get(code,0.0):+.2f}."
        )
        row = PricePredictionOut(
            driver_code=code,
            race_key=race_key,
            predicted_direction=direction,
            predicted_magnitude=mag,
            confidence=round(conf, 2),
            reasoning=reasoning[:220],
            signal_breakdown=breakdown,
            price_threshold_note=threshold_note,
        )
        rows.append(row)
        upserts.append(row.model_dump(mode="python"))

    await upsert_price_predictions(upserts)
    rows.sort(key=lambda r: abs(r.predicted_magnitude), reverse=True)
    return rows

