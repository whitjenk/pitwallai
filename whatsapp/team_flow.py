"""TEAM command — progressive fantasy team onboarding."""

from __future__ import annotations

import re

from db.models import FantasyTeam
from intelligence.repository import (
    get_fantasy_team,
    get_onboarding_state,
    set_onboarding_state,
    upsert_fantasy_team_fields,
)

_DRIVER_CODE_RE = re.compile(r"^[A-Z]{3}$")
_CONSTRUCTOR_CODE_RE = re.compile(r"^[A-Z]{2,4}$")


def _truncate(msg: str, limit: int = 160) -> str:
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def _team_drivers(team: FantasyTeam) -> list[str]:
    return [c for c in (team.driver_1, team.driver_2, team.driver_3, team.driver_4, team.driver_5) if c]


def _team_summary(team: FantasyTeam) -> str:
    drivers = ", ".join(_team_drivers(team)) or "—"
    constructors = ", ".join(c for c in (team.constructor_1, team.constructor_2) if c) or "—"
    budget = f"${team.remaining_budget:.1f}M" if team.remaining_budget is not None else "—"
    transfers = (
        "unlimited"
        if team.transfers_available >= 99
        else str(team.transfers_available)
    )
    return (
        f"Budget: {budget} | Drivers: {drivers} | "
        f"Constructors: {constructors} | Transfers: {transfers}"
    )


def _next_missing_step(team: FantasyTeam) -> int:
    """Return the first incomplete onboarding step (1–4)."""
    if team.remaining_budget is None:
        return 1
    if len(_team_drivers(team)) < 5:
        return 2
    if not team.constructor_1 or not team.constructor_2:
        return 3
    if team.transfers_available is None:
        return 4
    return 0


def _prompt_for_step(step: int) -> str:
    prompts = {
        1: "What's your remaining budget this week? (e.g. 2.1)",
        2: "Who are your 5 drivers? Reply with codes separated by commas (e.g. NOR, VER, LEC, ALB, HAM)",
        3: "Your 2 constructors? (e.g. MCL, RBR)",
        4: "Transfers available this week? (1, 2, or unlimited)",
    }
    return _truncate(f"PitWallAI TEAM: {prompts.get(step, 'Send TEAM to update your squad.')}")


def _parse_budget(text: str) -> float | None:
    cleaned = text.strip().replace("$", "").replace("M", "").replace("m", "")
    try:
        value = float(cleaned)
        return value if value >= 0 else None
    except ValueError:
        return None


def _parse_drivers(text: str) -> list[str] | None:
    parts = [p.strip().upper() for p in text.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 5:
        return None
    if not all(_DRIVER_CODE_RE.match(p) for p in parts):
        return None
    return parts


def _parse_constructors(text: str) -> tuple[str, str] | None:
    parts = [p.strip().upper() for p in text.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 2:
        return None
    if not all(_CONSTRUCTOR_CODE_RE.match(p) for p in parts):
        return None
    return parts[0], parts[1]


def _parse_transfers(text: str) -> int | None:
    raw = text.strip().lower()
    if raw in {"unlimited", "∞", "inf"}:
        return 99
    try:
        value = int(raw)
        return value if value in (0, 1, 2, 3) else None
    except ValueError:
        return None


async def handle_team_command(phone: str, text: str, raw_text: str) -> str:
    """
    Handle TEAM command and multi-step onboarding replies.

    Saves each answer immediately. Resumes from last incomplete step.
    """
    team = await get_fantasy_team(phone)
    state = await get_onboarding_state(phone)
    upper = text.strip().upper()

    if team is None:
        team = await upsert_fantasy_team_fields(phone)

    # Confirmation flow
    if state and state.awaiting_confirm:
        if upper in {"YES", "Y"}:
            await set_onboarding_state(phone, step=0, awaiting_confirm=False)
            team = await get_fantasy_team(phone)
            assert team is not None
            return _truncate(f"✅ Team saved. {_team_summary(team)}")
        if upper in {"NO", "N"}:
            await set_onboarding_state(phone, step=1, awaiting_confirm=False)
            return _prompt_for_step(1)
        return _truncate("Reply YES to confirm or NO to re-enter from budget.")

    # Completed profile — quick update path
    if _next_missing_step(team) == 0 and upper == "TEAM":
        return _truncate(f"✅ Team updated. {_team_summary(team)}")

    # Resume or start onboarding
    if upper == "TEAM":
        step = _next_missing_step(team) or 1
        await set_onboarding_state(phone, step=step, awaiting_confirm=False)
        return _prompt_for_step(step)

    step = state.step if state else _next_missing_step(team) or 1

    if step == 1:
        budget = _parse_budget(raw_text)
        if budget is None:
            return _truncate("Invalid budget. Example: 2.1")
        await upsert_fantasy_team_fields(phone, remaining_budget=budget)
        await set_onboarding_state(phone, step=2, awaiting_confirm=False)
        return _prompt_for_step(2)

    if step == 2:
        drivers = _parse_drivers(raw_text)
        if drivers is None:
            return _truncate("Need exactly 5 driver codes, comma-separated (e.g. NOR, VER, LEC, ALB, HAM).")
        await upsert_fantasy_team_fields(
            phone,
            driver_1=drivers[0],
            driver_2=drivers[1],
            driver_3=drivers[2],
            driver_4=drivers[3],
            driver_5=drivers[4],
        )
        await set_onboarding_state(phone, step=3, awaiting_confirm=False)
        return _prompt_for_step(3)

    if step == 3:
        constructors = _parse_constructors(raw_text)
        if constructors is None:
            return _truncate("Need 2 constructor codes, comma-separated (e.g. MCL, RBR).")
        await upsert_fantasy_team_fields(
            phone,
            constructor_1=constructors[0],
            constructor_2=constructors[1],
        )
        await set_onboarding_state(phone, step=4, awaiting_confirm=False)
        return _prompt_for_step(4)

    if step == 4:
        transfers = _parse_transfers(raw_text)
        if transfers is None:
            return _truncate("Reply 1, 2, or unlimited for transfers this week.")
        await upsert_fantasy_team_fields(phone, transfers_available=transfers)
        team = await get_fantasy_team(phone)
        assert team is not None
        await set_onboarding_state(phone, step=0, awaiting_confirm=True)
        return _truncate(f"Confirm team? {_team_summary(team)} — reply YES or NO")

    return _prompt_for_step(_next_missing_step(team) or 1)
