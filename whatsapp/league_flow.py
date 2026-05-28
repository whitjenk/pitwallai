"""LEAGUE command onboarding and updates."""

from __future__ import annotations

from datetime import UTC, datetime

from db.models import FantasyTeam, OpponentProfile
from intelligence.repository import (
    get_fantasy_team,
    get_league_onboarding_state,
    set_league_onboarding_state,
    upsert_fantasy_team_fields,
)

_VALID_STRATEGIES = {"SAFE", "ATTACK", "BALANCED"}
_VALID_TENDENCIES = {"PACE_CHASER", "VALUE_HUNTER", "HOLDS_STARS"}


def _truncate(msg: str, limit: int = 160) -> str:
    if len(msg) <= limit:
        return msg
    return msg[: limit - 3] + "..."


def _strategy_or_default(value: str | None) -> str:
    raw = (value or "").strip().upper()
    return raw if raw in _VALID_STRATEGIES else "BALANCED"


def _parse_int_in_range(raw_text: str, low: int, high: int) -> int | None:
    try:
        value = int(raw_text.strip())
    except ValueError:
        return None
    if value < low or value > high:
        return None
    return value


def _parse_yn_unsure(raw_text: str) -> bool | None:
    raw = raw_text.strip().upper()
    if raw in {"YES", "Y"}:
        return True
    if raw in {"NO", "N"}:
        return False
    if raw in {"UNSURE", "UNKNOWN"}:
        return None
    return None


def _team_summary(team: FantasyTeam) -> str:
    strategy = _strategy_or_default(team.league_strategy)
    return (
        f"League mode: {'ON' if team.league_mode_enabled else 'OFF'} | "
        f"Size {team.league_size or '—'} | Pos {team.league_position or '—'} | "
        f"Races {team.league_total_races or '—'} | Strategy {strategy} | "
        f"Opponents {len(team.opponent_profiles or [])}"
    )


async def handle_league_command(phone: str, text: str, raw_text: str) -> str:
    team = await get_fantasy_team(phone)
    if team is None:
        team = await upsert_fantasy_team_fields(phone)
    state = await get_league_onboarding_state(phone)
    upper = text.strip().upper()

    if upper == "LEAGUE UPDATE":
        await set_league_onboarding_state(phone, step=101, update_mode=True, awaiting_confirm=False)
        return _truncate("League update: what's your current position? (e.g. 3)")

    if state and state.update_mode:
        if state.step == 101:
            size = team.league_size or 20
            pos = _parse_int_in_range(raw_text, 1, max(1, size))
            if pos is None:
                return _truncate(f"Enter a position 1–{max(1, size)}.")
            await upsert_fantasy_team_fields(phone, league_position=pos, league_mode_enabled=True)
            await set_league_onboarding_state(phone, step=102, update_mode=True, awaiting_confirm=False)
            return _truncate("Reply SAFE, ATTACK, or BALANCED.")
        if state.step == 102:
            strategy = _strategy_or_default(raw_text)
            await upsert_fantasy_team_fields(phone, league_strategy=strategy, league_mode_enabled=True)
            await set_league_onboarding_state(phone, step=0, update_mode=False, awaiting_confirm=False)
            team = await get_fantasy_team(phone)
            assert team is not None
            return _truncate(f"✅ League updated. {_team_summary(team)}")

    if upper == "LEAGUE":
        await set_league_onboarding_state(phone, step=1, update_mode=False, awaiting_confirm=False)
        return _truncate("League mode on! How many people in your league? (2–20)")

    if state is None or state.step <= 0:
        return _truncate("Text LEAGUE to set up league-aware picks.")

    if state.awaiting_confirm:
        if upper in {"YES", "Y"}:
            await upsert_fantasy_team_fields(phone, league_mode_enabled=True)
            await set_league_onboarding_state(phone, step=0, awaiting_confirm=False)
            team = await get_fantasy_team(phone)
            assert team is not None
            return _truncate(f"✅ League saved. {_team_summary(team)}")
        if upper in {"NO", "N"}:
            await set_league_onboarding_state(phone, step=1, awaiting_confirm=False, draft_opponents=[])
            return _truncate("Restarted. How many people in your league? (2–20)")
        return _truncate("Reply YES to confirm or NO to restart LEAGUE setup.")

    # Step 1
    if state.step == 1:
        size = _parse_int_in_range(raw_text, 2, 20)
        if size is None:
            return _truncate("Enter league size as an integer 2–20.")
        await upsert_fantasy_team_fields(phone, league_size=size, league_mode_enabled=True)
        await set_league_onboarding_state(phone, step=2, draft_opponents=list(team.opponent_profiles or []))
        return _truncate("What's your current position? (e.g. 3)")

    # Step 2
    if state.step == 2:
        size = team.league_size or 20
        pos = _parse_int_in_range(raw_text, 1, size)
        if pos is None:
            return _truncate(f"Position must be 1–{size}.")
        await upsert_fantasy_team_fields(phone, league_position=pos)
        await set_league_onboarding_state(
            phone,
            step=3,
            draft_opponents=list(state.draft_opponents or team.opponent_profiles or []),
        )
        return _truncate("How many races have been scored so far this season?")

    # Step 3
    if state.step == 3:
        races = _parse_int_in_range(raw_text, 0, 50)
        if races is None:
            return _truncate("Enter races scored as an integer 0–50.")
        await upsert_fantasy_team_fields(phone, league_total_races=races)
        await set_league_onboarding_state(
            phone,
            step=4,
            draft_opponents=list(state.draft_opponents or team.opponent_profiles or []),
        )
        return _truncate(
            "SAFE=protect lead, ATTACK=close gap, BALANCED=middle. Reply SAFE, ATTACK, or BALANCED."
        )

    # Step 4
    if state.step == 4:
        strategy = _strategy_or_default(raw_text)
        await upsert_fantasy_team_fields(phone, league_strategy=strategy)
        await set_league_onboarding_state(
            phone,
            step=5,
            draft_opponents=list(state.draft_opponents or team.opponent_profiles or []),
        )
        return _truncate(
            "Add an opponent? Reply nickname or SKIP to finish."
        )

    opponents = list(state.draft_opponents or team.opponent_profiles or [])

    # Step 5 entry
    if state.step == 5:
        if upper in {"SKIP", "DONE"}:
            await upsert_fantasy_team_fields(
                phone,
                opponent_profiles=opponents,
                league_strategy=_strategy_or_default(team.league_strategy),
            )
            team = await get_fantasy_team(phone)
            assert team is not None
            await set_league_onboarding_state(phone, step=6, awaiting_confirm=True, draft_opponents=opponents)
            return _truncate(f"Confirm league setup? {_team_summary(team)} — reply YES or NO")
        nick = raw_text.strip()
        if not nick:
            return _truncate("Reply with a nickname or SKIP.")
        await set_league_onboarding_state(
            phone,
            step=51,
            pending_nickname=nick[:40],
            draft_opponents=opponents,
        )
        return _truncate(f"What drivers does {nick[:40]} usually pick? Codes or SKIP")

    if state.step == 51:
        nick = (state.pending_nickname or "Opponent").strip()
        known_drivers: list[str] = []
        if upper != "SKIP":
            known_drivers = [p.strip().upper() for p in raw_text.replace(";", ",").split(",") if p.strip()]
        profile = OpponentProfile(
            nickname=nick[:40],
            estimated_budget=None,
            known_drivers=known_drivers[:10],
            tendency=None,
            chip_wildcard_used=False,
            chip_limitless_used=False,
            chip_megadrivers_used=False,
            last_updated=datetime.now(tz=UTC),
        )
        opponents.append(profile.model_dump(mode="json"))
        await set_league_onboarding_state(phone, step=52, draft_opponents=opponents, pending_nickname=nick[:40])
        return _truncate(f"Has {nick[:40]} used Wildcard? YES / NO / UNSURE")

    if state.step == 52:
        nick = state.pending_nickname or "Opponent"
        val = _parse_yn_unsure(raw_text)
        if val is None and upper not in {"UNSURE", "UNKNOWN"}:
            return _truncate("Reply YES, NO, or UNSURE.")
        if opponents:
            opponents[-1]["chip_wildcard_used"] = bool(val) if val is not None else False
            opponents[-1]["last_updated"] = datetime.now(tz=UTC).isoformat()
        await set_league_onboarding_state(phone, step=53, draft_opponents=opponents, pending_nickname=nick)
        return _truncate(f"Has {nick[:40]} used Limitless? YES / NO / UNSURE")

    if state.step == 53:
        val = _parse_yn_unsure(raw_text)
        if val is None and upper not in {"UNSURE", "UNKNOWN"}:
            return _truncate("Reply YES, NO, or UNSURE.")
        if opponents:
            opponents[-1]["chip_limitless_used"] = bool(val) if val is not None else False
            opponents[-1]["last_updated"] = datetime.now(tz=UTC).isoformat()
        await upsert_fantasy_team_fields(phone, opponent_profiles=opponents)
        await set_league_onboarding_state(phone, step=5, draft_opponents=opponents, pending_nickname=None)
        return _truncate("Add another? Reply nickname or DONE")

    return _truncate("Text LEAGUE to continue setup.")

