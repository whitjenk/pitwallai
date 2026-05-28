"""Driver price history seeding and lookup."""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

from fantasy.rules import DRIVER_PRICES_M, driver_points_qualifying, driver_points_race
from intelligence.drivers import driver_code_for
from intelligence.repository import (
    get_all_current_prices as _repo_get_all_current_prices,
    get_price_history as _repo_get_price_history,
    is_driver_price_history_empty,
    save_driver_price_rows,
)
from openf1.client import OpenF1Client

_REDDIT_WIKI_URL = "https://www.reddit.com/r/FantasyF1/wiki/pricechanges.json"
_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "price_history_2025.csv"

_RACES_2025: tuple[str, ...] = (
    "2025_bahrain",
    "2025_jeddah",
    "2025_melbourne",
    "2025_suzuka",
    "2025_shanghai",
    "2025_miami",
    "2025_imola",
    "2025_monaco",
    "2025_barcelona",
    "2025_montreal",
    "2025_spielberg",
    "2025_silverstone",
    "2025_spa",
    "2025_hungaroring",
    "2025_zandvoort",
    "2025_monza",
    "2025_baku",
    "2025_marina_bay",
    "2025_austin",
    "2025_mexico_city",
    "2025_interlagos",
    "2025_las_vegas",
    "2025_lusail",
    "2025_yas_marina",
)

_CIRCUIT_TO_OPENF1: dict[str, str] = {
    "bahrain": "Sakhir",
    "jeddah": "Jeddah",
    "melbourne": "Melbourne",
    "suzuka": "Suzuka",
    "shanghai": "Shanghai",
    "miami": "Miami",
    "imola": "Imola",
    "monaco": "Monaco",
    "barcelona": "Barcelona",
    "montreal": "Montreal",
    "spielberg": "Spielberg",
    "silverstone": "Silverstone",
    "spa": "Spa-Francorchamps",
    "hungaroring": "Hungaroring",
    "zandvoort": "Zandvoort",
    "monza": "Monza",
    "baku": "Baku",
    "marina_bay": "Singapore",
    "austin": "Austin",
    "mexico_city": "Mexico City",
    "interlagos": "Interlagos",
    "las_vegas": "Las Vegas",
    "lusail": "Lusail",
    "yas_marina": "Yas Marina Circuit",
}


def _season_start_prices() -> dict[str, float]:
    return {code: float(price) for code, price in DRIVER_PRICES_M.items()}


def _load_csv_rows() -> list[dict[str, Any]]:
    if not _CSV_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    with _CSV_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            out.append(
                {
                    "driver_code": row["driver_code"].strip().upper(),
                    "race_key": row["race_key"].strip(),
                    "price": float(row["price"]),
                    "price_change": float(row["price_change"]) if row.get("price_change") else None,
                    "fantasy_points_scored": (
                        float(row["fantasy_points_scored"]) if row.get("fantasy_points_scored") else None
                    ),
                    "ownership_pct": float(row["ownership_pct"]) if row.get("ownership_pct") else None,
                }
            )
    return out


def _generate_fallback_rows() -> list[dict[str, Any]]:
    """Deterministic fallback if CSV is unavailable."""
    prices = _season_start_prices()
    rows: list[dict[str, Any]] = []
    codes = list(prices.keys())
    for race_idx, race_key in enumerate(_RACES_2025):
        for i, code in enumerate(codes):
            direction = ((race_idx + i) % 3) - 1  # -1,0,+1
            delta = round(0.1 * direction, 1)
            price = round(max(3.0, prices[code] + delta), 1)
            rows.append(
                {
                    "driver_code": code,
                    "race_key": race_key,
                    "price": price,
                    "price_change": delta,
                    "fantasy_points_scored": None,
                    "ownership_pct": None,
                }
            )
            prices[code] = price
    return rows


async def _derive_points_for_2025(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_race_driver: dict[tuple[str, str], dict[str, Any]] = {(r["race_key"], r["driver_code"]): r for r in rows}
    client = OpenF1Client()
    for race_key in _RACES_2025:
        _, circuit = race_key.split("_", 1)
        openf1_circuit = _CIRCUIT_TO_OPENF1.get(circuit)
        if not openf1_circuit:
            continue
        race_sk = await client.find_session_key(year=2025, circuit_short_name=openf1_circuit, session_name="Race")
        quali_sk = await client.find_session_key(year=2025, circuit_short_name=openf1_circuit, session_name="Qualifying")
        race_results = await client.get_session_results(race_sk) if race_sk else []
        quali_results = await client.get_session_results(quali_sk) if quali_sk else []
        grid_by_code: dict[str, int] = {}
        for q in quali_results:
            if q.position is None:
                continue
            grid_by_code[driver_code_for(q.driver_number)] = int(q.position)
        for rr in race_results:
            code = driver_code_for(rr.driver_number)
            key = (race_key, code)
            if key not in by_race_driver:
                continue
            pts = 0.0
            pos = rr.position
            if rr.dsq:
                pts = -20.0
            elif rr.dnf:
                pts = -15.0
            elif pos is not None:
                pts += float(driver_points_race(pos))
            if code in grid_by_code and pos is not None:
                pts += max(0, (grid_by_code[code] - pos) * 2)
                pts += float(driver_points_qualifying(grid_by_code[code]))
            by_race_driver[key]["fantasy_points_scored"] = round(pts, 1)
    return rows


async def _load_from_reddit_wiki() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "PitWallAI/1.0"}) as client:
            resp = await client.get(_REDDIT_WIKI_URL)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return []
    text = str(((payload.get("data") or {}).get("content_md") or "")).strip()
    if not text:
        return []
    # Heuristic parser intentionally conservative; empty means fallback.
    return []


async def seed_price_history() -> int:
    """
    Seed immutable price history once.

    Returns number of inserted rows.
    """
    if not await is_driver_price_history_empty():
        logger.info("Price history already seeded")
        return 0

    rows = await _load_from_reddit_wiki()
    if not rows:
        rows = _load_csv_rows()
    if not rows:
        rows = _generate_fallback_rows()
    rows = await _derive_points_for_2025(rows)
    created = await save_driver_price_rows(rows)
    logger.info("seed_price_history completed rows={}", created)
    return created


async def get_price_history(driver_code: str, last_n_races: int = 10):
    return await _repo_get_price_history(driver_code, last_n_races=last_n_races)


async def get_all_current_prices() -> dict[str, float]:
    return await _repo_get_all_current_prices()

