"""Season recap computation from pick audit and signal quality data."""

from __future__ import annotations

import hashlib
import hmac
from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass

from sqlalchemy import select

from db.models import PickRow, SignalQualityRow
from db.session import get_session
from intelligence.recap_metrics import (
    avg_points_delta,
    hit_rate_pct,
    momentum_delta_pp,
    momentum_trend,
    prev_race_key,
)
from scheduler.calendar import CALENDAR_2026


@dataclass(frozen=True, slots=True)
class SeasonRecap:
    season: int
    personalized_accuracy_pct: float
    community_accuracy_pct: float
    best_call: str
    worst_call: str
    biggest_signal: str
    share_url: str


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Latest scored race weekend for share-page session strip."""

    circuit_label: str
    hit_pct: float
    avg_points_delta: float
    momentum_trend: str
    momentum_delta_pp: int | None


def _accuracy_pct(rows: list[PickRow]) -> float:
    if not rows:
        return 0.0
    correct = sum(1 for row in rows if row.was_correct)
    return round(100.0 * correct / len(rows), 1)


def _pick_label(row: PickRow) -> str:
    race = row.circuit_key.replace("_", " ").title()
    if row.transfer_in:
        return f"{row.transfer_in} at {race}"
    return f"{row.driver_code} at {race}"


def _best_and_worst_calls(rows: list[PickRow]) -> tuple[str, str]:
    scored = [row for row in rows if row.actual_points_delta is not None]
    if not scored:
        return ("n/a", "n/a")
    best = max(scored, key=lambda row: float(row.actual_points_delta or 0.0))
    worst = min(scored, key=lambda row: float(row.actual_points_delta or 0.0))
    best_label = f"{_pick_label(best)} (+{int(round(float(best.actual_points_delta or 0.0)))} pts)"
    worst_delta = int(round(abs(float(worst.actual_points_delta or 0.0))))
    worst_label = f"{_pick_label(worst)} (-{worst_delta} pts)"
    return (best_label, worst_label)


async def _biggest_signal_for_season() -> str:
    async with get_session() as session:
        result = await session.execute(select(SignalQualityRow))
        rows = list(result.scalars().all())
    if not rows:
        return "No dominant signal yet"
    by_signal: dict[str, list[float]] = {}
    for row in rows:
        by_signal.setdefault(row.signal_type, []).append(float(row.hit_rate))
    top_signal = "practice_sentiment"
    top_rate = -1.0
    for signal_type, values in by_signal.items():
        avg = sum(values) / len(values)
        if avg > top_rate:
            top_rate = avg
            top_signal = signal_type
    signal_readable = top_signal.replace("_", " ")
    return f"{signal_readable} was {int(round(top_rate * 100))}% predictive"


def build_share_token(phone: str, season: int, secret: str) -> str:
    """Signed share token that can be verified server-side."""
    payload = f"{phone}:{season}"
    payload_b64 = urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    key = secret.encode("utf-8")
    digest = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return f"{payload_b64}.{digest}"


def parse_share_token(token: str, secret: str) -> tuple[str, int] | None:
    """Decode and verify share token, returning (phone, season)."""
    if "." not in token:
        return None
    payload_b64, sig = token.split(".", 1)
    if not payload_b64 or not sig:
        return None
    pad = "=" * ((4 - len(payload_b64) % 4) % 4)
    try:
        payload = urlsafe_b64decode((payload_b64 + pad).encode("ascii")).decode("utf-8")
    except Exception:
        return None
    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:20]
    if not hmac.compare_digest(expected, sig):
        return None
    if ":" not in payload:
        return None
    phone, season_raw = payload.rsplit(":", 1)
    try:
        season = int(season_raw)
    except ValueError:
        return None
    return (phone, season)


async def _picks_for_race(
    phone: str,
    race_key: str,
    *,
    personalized: bool,
) -> list[PickRow]:
    async with get_session() as session:
        stmt = select(PickRow).where(
            PickRow.race_key == race_key,
            PickRow.was_correct.is_not(None),
        )
        if personalized:
            stmt = stmt.where(PickRow.phone == phone, PickRow.personalized.is_(True))
        else:
            stmt = stmt.where(PickRow.phone.is_(None))
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def build_latest_session_snapshot(phone: str, season: int) -> SessionSnapshot | None:
    """Most recent scored weekend with optional momentum vs prior race."""
    prefix = f"{season}_"
    calendar_keys = [w.race_key for w in CALENDAR_2026 if w.race_key.startswith(prefix)]
    latest_key: str | None = None
    latest_picks: list[PickRow] = []
    for race_key in reversed(calendar_keys):
        picks = await _picks_for_race(phone, race_key, personalized=True)
        if not picks:
            picks = await _picks_for_race(phone, race_key, personalized=False)
        if picks:
            latest_key = race_key
            latest_picks = picks
            break
    if latest_key is None or not latest_picks:
        return None

    weekend = next((w for w in CALENDAR_2026 if w.race_key == latest_key), None)
    circuit_label = weekend.display_name if weekend else latest_key.replace("_", " ").title()
    hit = hit_rate_pct(latest_picks)
    prev_key = prev_race_key(latest_key)
    prev_hit: float | None = None
    if prev_key:
        prev_picks = await _picks_for_race(phone, prev_key, personalized=True)
        if not prev_picks:
            prev_picks = await _picks_for_race(phone, prev_key, personalized=False)
        if prev_picks:
            prev_hit = hit_rate_pct(prev_picks)
    delta = momentum_delta_pp(hit, prev_hit)
    return SessionSnapshot(
        circuit_label=circuit_label,
        hit_pct=round(hit, 1),
        avg_points_delta=round(avg_points_delta(latest_picks), 1),
        momentum_trend=momentum_trend(delta),
        momentum_delta_pp=delta,
    )


async def build_season_recap(
    *,
    phone: str,
    season: int,
    share_base_url: str,
    share_secret: str,
) -> SeasonRecap:
    """Build per-user season recap from audit log."""
    prefix = f"{season}_"
    async with get_session() as session:
        personal_result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{prefix}%"),
                PickRow.phone == phone,
                PickRow.personalized.is_(True),
                PickRow.was_correct.is_not(None),
            )
        )
        personal_rows = list(personal_result.scalars().all())

        community_result = await session.execute(
            select(PickRow).where(
                PickRow.race_key.like(f"{prefix}%"),
                PickRow.phone.is_(None),
                PickRow.was_correct.is_not(None),
            )
        )
        community_rows = list(community_result.scalars().all())

    best_call, worst_call = _best_and_worst_calls(personal_rows)
    biggest_signal = await _biggest_signal_for_season()
    token = build_share_token(phone=phone, season=season, secret=share_secret)
    share_url = f"{share_base_url.rstrip('/')}/you/{token}"
    return SeasonRecap(
        season=season,
        personalized_accuracy_pct=_accuracy_pct(personal_rows),
        community_accuracy_pct=_accuracy_pct(community_rows),
        best_call=best_call,
        worst_call=worst_call,
        biggest_signal=biggest_signal,
        share_url=share_url,
    )
