"""League ownership proxies: PitWallAI aggregate + community buzz heuristic."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import re

import httpx
from pydantic import BaseModel, ConfigDict

from fantasy.rules import DRIVER_PRICES_M
from intelligence.repository import load_latest_pick_ownership

_REDDIT_URL = "https://www.reddit.com/r/FantasyF1/search.json"
_USER_AGENT = "PitWallAI/1.0 (ownership heuristic)"
_CACHE: dict[str, tuple[datetime, dict[str, "OwnershipData"]]] = {}
_CACHE_TTL_S = 900

_DRIVER_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "VER": ("VER", "MAX", "VERSTAPPEN"),
    "NOR": ("NOR", "LANDO", "NORRIS"),
    "LEC": ("LEC", "CHARLES", "LECLERC"),
    "PIA": ("PIA", "PIASTRI", "OSCAR"),
    "HAM": ("HAM", "LEWIS", "HAMILTON"),
    "RUS": ("RUS", "GEORGE", "RUSSELL"),
    "SAI": ("SAI", "CARLOS", "SAINZ"),
    "ALO": ("ALO", "FERNANDO", "ALONSO"),
    "PER": ("PER", "PEREZ", "CHECO"),
}


class OwnershipData(BaseModel):
    """Ownership proxy for a single driver."""

    model_config = ConfigDict(frozen=True)

    race_key: str
    driver_code: str
    pitwallai_ownership_pct: float | None
    community_ownership_pct: float | None
    combined_ownership_pct: float | None
    ownership_tier: str


def _tier(combined: float | None) -> str:
    if combined is None:
        return "UNKNOWN"
    if combined > 50.0:
        return "HIGH"
    if combined >= 20.0:
        return "MEDIUM"
    return "LOW"


def _combine(pitwall: float | None, community: float | None) -> float | None:
    if pitwall is None and community is None:
        return None
    if pitwall is None:
        return community
    if community is None:
        return pitwall
    return round(0.6 * pitwall + 0.4 * community, 1)


def _tokenize(text: str) -> set[str]:
    return {tok.upper() for tok in re.findall(r"[A-Za-z]{2,}", text)}


def _infer_community_buzz(comments: list[str]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for comment in comments:
        tokens = _tokenize(comment)
        for code, aliases in _DRIVER_NAME_ALIASES.items():
            if any(alias in tokens for alias in aliases):
                counts[code] += 1
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {code: round(100.0 * count / total, 1) for code, count in counts.items()}


async def _fetch_reddit_buzz() -> dict[str, float]:
    """Best-effort community buzz proxy from Reddit comment mentions."""
    params = {"q": "race week picks", "sort": "new", "limit": 5}
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": _USER_AGENT}) as client:
            resp = await client.get(_REDDIT_URL, params=params)
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return {}

    comments: list[str] = []
    for child in ((payload.get("data") or {}).get("children") or []):
        data = child.get("data") or {}
        text = str(data.get("selftext", "") or "")
        if text:
            comments.append(text)
    return _infer_community_buzz(comments)


async def get_ownership_data(race_key: str) -> dict[str, OwnershipData]:
    """
    Return ownership proxies for all drivers for this race.

    Cache is race-scoped for the weekend to avoid repeated remote fetches.
    """
    now = datetime.now(tz=UTC)
    cached = _CACHE.get(race_key)
    if cached and (now - cached[0]).total_seconds() < _CACHE_TTL_S:
        return cached[1]

    pit_rows = await load_latest_pick_ownership(race_key)
    pit_pct = {code: round(row.pitwallai_ownership_pct, 1) for code, row in pit_rows.items()}
    community_pct = await _fetch_reddit_buzz()

    payload: dict[str, OwnershipData] = {}
    for code in DRIVER_PRICES_M.keys():
        pit = pit_pct.get(code)
        comm = community_pct.get(code)
        combined = _combine(pit, comm)
        payload[code] = OwnershipData(
            race_key=race_key,
            driver_code=code,
            pitwallai_ownership_pct=pit,
            community_ownership_pct=comm,
            combined_ownership_pct=combined,
            ownership_tier=_tier(combined),
        )

    _CACHE[race_key] = (now, payload)
    return payload

