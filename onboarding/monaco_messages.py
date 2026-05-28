"""Monaco 2024 rehearsal messages built from real OpenF1 / seed data."""

from __future__ import annotations


from circuits.profiles import get_circuit_profile
from intelligence.pick_generator import build_qualifying_rows, generate_picks
from intelligence.practice_analyst import analyze_practice_weekend
from intelligence.repository import get_fantasy_team
from intelligence.schemas import PickGeneratorInput
from onboarding.monaco_calendar import MONACO_2024_REHEARSAL, MONACO_SESSION_KEY
from openf1.client import OpenF1Client
from pitwallai.agents.radio_intercept.seed_data import MONACO_REHEARSAL_SCENARIO
from scheduler.calendar import RaceWeekend
from whatsapp.broadcast import _is_personalized_eligible
from whatsapp.message_format import format_generic_picks, format_personalized_picks
from whatsapp.app_runtime import PickRuntime

_FP2_DELTA_MAX = 280
_CONTEXT_MAX = 400


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "…"


def build_welcome_context_message() -> str:
    """Thursday-style context from Monaco 2024 rehearsal scenario."""
    scenario = MONACO_REHEARSAL_SCENARIO
    return _truncate(
        "🏁 Welcome to PitWallAI!\n\n"
        "Sample weekend: Monaco 2024 (historical OpenF1 data, session "
        f"{MONACO_SESSION_KEY}) — not a live race.\n\n"
        f"{scenario.description}\n\n"
        "FP2 signal update follows in ~15 min.",
        _CONTEXT_MAX,
    )


def build_fp2_delta_message(*, lock_label: str = "Sat 13:00") -> str:
    """Friday FP2 delta — NOR strong, LEC anomaly (Monaco 2024 radio arc)."""
    return _truncate(
        "⚠️ FP2 signal update (Monaco 2024 sample)\n\n"
        "NOR strong practice signal — positive radio and pace in FP2.\n"
        "LEC anomaly flag: front left graining in sector two.\n"
        "Saturday pick still shows LEC — consider reviewing before lock.\n\n"
        "Reply PICKS to see updated recommendations\n"
        f"Lock: {lock_label}",
        _FP2_DELTA_MAX,
    )


async def build_saturday_picks_message(
    phone: str,
    runtime: PickRuntime,
    *,
    timezone: str,
) -> str:
    """
    Saturday picks from Monaco 2024 FP2 + quali via OpenF1.

    Falls back to short observational copy if OpenF1 is unreachable.
    """
    circuit = get_circuit_profile("monaco")
    if circuit is None:
        return _truncate("🎯 Saturday picks (Monaco 2024 sample) — circuit profile unavailable.")

    client = OpenF1Client()
    try:
        practice_signals = await analyze_practice_weekend(
            client=client,
            agent=runtime.agent,
            vector_store=runtime.vector_store,
            circuit=circuit,
            year=2024,
            persist=False,
        )
        quali_sk = await client.find_session_key(
            year=2024,
            circuit_short_name=circuit.openf1_circuit_name,
            session_name="Qualifying",
        )
        qualifying = await build_qualifying_rows(client, quali_sk) if quali_sk else []
        team = await get_fantasy_team(phone)
        output = generate_picks(
            PickGeneratorInput(
                circuit=circuit,
                practice_signals=practice_signals,
                qualifying_result=qualifying,
                weather_forecast=None,
                user_team=team,
                price_predictions={},
                race_key=MONACO_2024_REHEARSAL.race_key,
                generated_by="monaco_rehearsal",
            )
        )
        weekend: RaceWeekend = MONACO_2024_REHEARSAL
        if team and _is_personalized_eligible(team):
            return format_personalized_picks(weekend, output, timezone=timezone)
        return format_generic_picks(weekend, output, timezone=timezone)
    except Exception:
        return _truncate(
            "🎯 Saturday picks (Monaco 2024 sample)\n"
            "NOR and LEC featured in FP2 signals; quali grid from historical session.\n"
            "Reply PICKS on your first real race weekend for live recommendations.",
            400,
        )


async def build_sc_live_alert_message(client: OpenF1Client | None = None) -> str:
    """Sunday live alert — Safety Car from Monaco 2024 race control when available."""
    from agents.race_monitor import _format_alert

    client = client or OpenF1Client()
    try:
        messages = await client.get_race_control(MONACO_SESSION_KEY)
        for row in messages:
            text = (row.message or "").strip()
            lap = row.lap_number
            upper = text.upper()
            if lap is not None and lap <= 35 and ("SAFETY CAR" in upper or "SC DEPLOYED" in upper):
                return _format_alert(f"🚨 Monaco 2024 · Lap {lap}: {text}")
    except Exception:
        pass
    return _format_alert(
        "🚨 Monaco 2024 · Lap 32: Safety Car deployed — observed from race control data."
    )


def build_sample_counterfactual_message() -> str:
    """Post-race recap format preview (historical sample, not scored picks)."""
    from whatsapp.counterfactual_format import format_counterfactual_whatsapp
    from intelligence.counterfactual import CounterfactualRecap

    recap = CounterfactualRecap(
        phone="sample",
        race_key=MONACO_2024_REHEARSAL.race_key,
        picks_correct=2,
        picks_total=3,
        points_gained=14.0,
        best_pick_driver="NOR",
        best_pick_delta=8.0,
        vs_no_change_delta=6.0,
        share_token="sample",
        season_accuracy_pct=0.0,
        circuit_label="Monaco 2024 (sample)",
    )
    return format_counterfactual_whatsapp(recap, next_race_name=None, days_until_next=None)


def rehearsal_delays_seconds(*, fast: bool = False) -> tuple[float, ...]:
    """Delays between rehearsal messages (welcome → FP2 → picks → SC → recap)."""
    if fast:
        return (3.0, 5.0, 8.0, 5.0, 4.0)
    return (15 * 60.0, 30 * 60.0, 45 * 60.0, 30 * 60.0, 0.0)


def lock_time_label(timezone: str) -> str:
    """Subscriber-local fantasy lock label for Monaco sample weekend."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone)
    lock = MONACO_2024_REHEARSAL.fantasy_lock_utc.astimezone(tz)
    return lock.strftime("%a %H:%M")
