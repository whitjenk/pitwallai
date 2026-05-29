"""Post-race "what we called" recap — shareable evidence card.

RaceMonitor logs strategic moments during the race; this module renders
them after the flag as a forwardable card with the source-signal
timestamp and the decode timestamp side by side. Timestamps are vs.
the OpenF1 source signal, not vs. TV broadcast.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from orchestrator.race_context import RaceEvent, RaceEventType

# Event types that are interesting to surface as "we called it" moments.
# RACE_COMPLETE is housekeeping; weather changes are noisy; we keep the
# tactical strategic signals a fan would actually share.
_RECAP_EVENT_TYPES: frozenset[RaceEventType] = frozenset(
    {
        RaceEventType.SAFETY_CAR,
        RaceEventType.VIRTUAL_SC,
        RaceEventType.RED_FLAG,
        RaceEventType.RETIREMENT,
        RaceEventType.PIT_WINDOW_OPEN,
    }
)


@dataclass(frozen=True, slots=True)
class CalledMoment:
    """One forwardable "we called it" line."""

    event_type: RaceEventType
    lap: int | None
    driver_code: str | None
    description: str
    source_signal_utc: datetime
    decoded_at_utc: datetime | None
    decode_latency_seconds: float | None


@dataclass(frozen=True, slots=True)
class CalledRaceRecap:
    """Aggregate of the weekend's live-monitor calls."""

    race_key: str
    race_label: str
    moments: tuple[CalledMoment, ...]
    share_token: str
    data_unavailable: bool = False

    @property
    def moment_count(self) -> int:
        return len(self.moments)

    @property
    def median_decode_latency_seconds(self) -> float | None:
        """Median pipeline latency across called moments — credibility number."""
        latencies = sorted(
            m.decode_latency_seconds
            for m in self.moments
            if m.decode_latency_seconds is not None
        )
        if not latencies:
            return None
        mid = len(latencies) // 2
        if len(latencies) % 2 == 1:
            return latencies[mid]
        return (latencies[mid - 1] + latencies[mid]) / 2


def build_called_recap(
    *,
    race_key: str,
    race_label: str,
    events: list[RaceEvent],
    data_unavailable: bool = False,
) -> CalledRaceRecap:
    """Filter race events to forwardable moments and build the recap."""
    moments: list[CalledMoment] = []
    for ev in events:
        if ev.event_type not in _RECAP_EVENT_TYPES:
            continue
        moments.append(
            CalledMoment(
                event_type=ev.event_type,
                lap=ev.lap,
                driver_code=ev.driver_code,
                description=ev.description,
                source_signal_utc=ev.utc_timestamp,
                decoded_at_utc=ev.decoded_at_utc,
                decode_latency_seconds=ev.decode_latency_seconds,
            )
        )
    return CalledRaceRecap(
        race_key=race_key,
        race_label=race_label,
        moments=tuple(moments),
        share_token=str(uuid.uuid4()),
        data_unavailable=data_unavailable,
    )


_EVENT_GLYPH: dict[RaceEventType, str] = {
    RaceEventType.SAFETY_CAR: "🟡",
    RaceEventType.VIRTUAL_SC: "🟡",
    RaceEventType.RED_FLAG: "🔴",
    RaceEventType.RETIREMENT: "🏳️",
    RaceEventType.PIT_WINDOW_OPEN: "⚡",
}


def _event_label(et: RaceEventType) -> str:
    return {
        RaceEventType.SAFETY_CAR: "Safety car",
        RaceEventType.VIRTUAL_SC: "VSC",
        RaceEventType.RED_FLAG: "Red flag",
        RaceEventType.RETIREMENT: "Retirement",
        RaceEventType.PIT_WINDOW_OPEN: "Pit window",
    }.get(et, et.value)


def render_called_recap_whatsapp(recap: CalledRaceRecap, share_url: str | None) -> str:
    """Sunday-night forwardable WhatsApp message."""
    if recap.data_unavailable and not recap.moments:
        return (
            f"📡 *{recap.race_label} — live data unavailable*\n\n"
            "OpenF1 was unreachable during the race, so PitWallAI couldn't "
            "log strategic moments. This is *not* a quiet-race verdict — "
            "we simply don't have receipts for this one.\n\n"
            "──────────────────\n"
            "PitWallAI · Not financial advice"
        )
    if not recap.moments:
        return (
            f"📡 *{recap.race_label} — zero strategic moments*\n\n"
            "PitWallAI counts the moments that mattered. "
            "This weekend, none cleared the bar. "
            "A clean processional race is a verdict, not an absence.\n\n"
            "──────────────────\n"
            "PitWallAI · Not financial advice"
        )

    lines: list[str] = [f"📡 *{recap.race_label} — what we called*", ""]
    for m in recap.moments[:5]:
        glyph = _EVENT_GLYPH.get(m.event_type, "·")
        who = f" {m.driver_code}" if m.driver_code else ""
        lap = f"L{m.lap}" if m.lap is not None else "—"
        hhmm = m.source_signal_utc.strftime("%H:%M:%S")
        lines.append(f"{glyph} {lap}{who} — {_event_label(m.event_type)} ({hhmm} UTC)")

    median = recap.median_decode_latency_seconds
    if median is not None:
        lines.append("")
        lines.append(
            f"Median decode latency vs. source signal: {median:.1f}s "
            f"across {recap.moment_count} call-out(s)."
        )

    if share_url:
        lines.append("")
        lines.append(f"Full receipts: {share_url}")

    lines.extend(["", "──────────────────", "PitWallAI · Not financial advice"])
    return "\n".join(lines)


def recap_to_json(recap: CalledRaceRecap) -> dict[str, Any]:
    """Serialize for persistence in the share-card store."""
    return {
        "race_key": recap.race_key,
        "race_label": recap.race_label,
        "share_token": recap.share_token,
        "data_unavailable": recap.data_unavailable,
        "moments": [
            {
                "event_type": m.event_type.value,
                "lap": m.lap,
                "driver_code": m.driver_code,
                "description": m.description,
                "source_signal_utc": m.source_signal_utc.isoformat(),
                "decoded_at_utc": (
                    m.decoded_at_utc.isoformat() if m.decoded_at_utc else None
                ),
                "decode_latency_seconds": m.decode_latency_seconds,
            }
            for m in recap.moments
        ],
    }


async def generate_and_persist_called_recap(
    *,
    race_key: str,
    race_label: str,
) -> CalledRaceRecap:
    """Sunday-night entry point: pull events from DB, build recap, persist."""
    from intelligence.repository import get_monitor_state, list_race_events, save_called_recap

    events = await list_race_events(race_key)
    state = await get_monitor_state(race_key)
    data_unavailable = bool(state and state.data_unavailable)
    recap = build_called_recap(
        race_key=race_key,
        race_label=race_label,
        events=events,
        data_unavailable=data_unavailable,
    )
    await save_called_recap(race_key, recap.share_token, recap_to_json(recap))
    return recap


async def load_called_recap(share_token: str) -> CalledRaceRecap | None:
    from intelligence.repository import get_called_recap_by_token

    row = await get_called_recap_by_token(share_token)
    if row is None:
        return None
    return recap_from_json(row.recap_json)


def recap_from_json(data: dict[str, Any]) -> CalledRaceRecap:
    moments = tuple(
        CalledMoment(
            event_type=RaceEventType(m["event_type"]),
            lap=m.get("lap"),
            driver_code=m.get("driver_code"),
            description=m.get("description", ""),
            source_signal_utc=datetime.fromisoformat(m["source_signal_utc"]),
            decoded_at_utc=(
                datetime.fromisoformat(m["decoded_at_utc"])
                if m.get("decoded_at_utc")
                else None
            ),
            decode_latency_seconds=m.get("decode_latency_seconds"),
        )
        for m in data.get("moments", [])
    )
    return CalledRaceRecap(
        race_key=data["race_key"],
        race_label=data["race_label"],
        moments=moments,
        share_token=data.get("share_token", ""),
        data_unavailable=bool(data.get("data_unavailable", False)),
    )
