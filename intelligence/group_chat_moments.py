"""Group-chat-moment broadcasts: Friday "what changed" + Monday post-mortem.

The user's JTBD isn't picks, it's social currency in their league chat.
These broadcasts produce forwardable moments at the two highest-emotion
beats of the week:

  * Friday    — "here's what changed since you last looked"
  * Monday    — "here's how you did vs your league"

Both are scaffolded but FLAGGED OFF until they're proven to produce lift.
Lifts will be measured via group-chat forward rate (instrumented separately)
and retention against a control cohort.
"""

from __future__ import annotations

from dataclasses import dataclass

from db.models import FantasyTeam, PickRow


# ── Friday "what changed" ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FridayDigest:
    """Diff between Thursday context and Friday post-FP2 view."""

    race_label: str
    movers: list[tuple[str, str]]   # (driver_code, one-line "why moved")
    new_risks: list[str]


def render_friday_digest(digest: FridayDigest) -> str:
    """Forwardable Friday digest. Plain text — designed to travel."""
    if not digest.movers and not digest.new_risks:
        return ""  # nothing material changed; don't send

    lines = [f"📡 *{digest.race_label} — what changed*", ""]
    for code, why in digest.movers[:3]:
        lines.append(f"*{code}* — {why}")
    if digest.new_risks:
        lines.append("")
        for risk in digest.new_risks[:2]:
            lines.append(f"⚠️  {risk}")
    lines.extend(["", "──────────────────", "PitWallAI · Not financial advice"])
    return "\n".join(lines)


# ── Monday league post-mortem ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LeaguePostMortem:
    """What the user could share in their league chat on Monday."""

    race_label: str
    user_position: int | None
    leader_name: str | None
    leader_key_pick: str | None        # driver_code the leader had that user didn't
    pitwallai_score_pct: float          # PitWallAI's pick hit rate this weekend
    user_score_pct: float | None        # User's hit rate vs PitWallAI's picks
    counterfactual_swing: int | None   # pts gained if user had followed PitWallAI


def render_league_postmortem(pm: LeaguePostMortem) -> str:
    """Forwardable Monday post-mortem. Tone: honest, specific, league-aware."""
    lines = [f"🏁 *{pm.race_label} — your week*", ""]
    if pm.user_position is not None:
        lines.append(f"You finished *P{pm.user_position}* in your league.")
    if pm.leader_name and pm.leader_key_pick:
        lines.append(f"Leader *{pm.leader_name}* had *{pm.leader_key_pick}* — you didn't.")
    elif pm.leader_name:
        lines.append(f"Leader: *{pm.leader_name}*.")
    if pm.counterfactual_swing is not None:
        sign = "+" if pm.counterfactual_swing >= 0 else ""
        lines.append(f"Following PitWallAI fully would have been {sign}{pm.counterfactual_swing} pts.")
    lines.append(
        f"PitWallAI hit rate this weekend: *{pm.pitwallai_score_pct:.0f}%*."
    )
    lines.extend(["", "──────────────────", "PitWallAI · Not financial advice"])
    return "\n".join(lines)


def build_league_postmortem_from_data(
    race_label: str,
    user_picks: list[PickRow],
    league_team: FantasyTeam | None,
    pitwallai_hit_rate: float,
) -> LeaguePostMortem:
    """Cold-start safe — gracefully degrades when league data is missing.

    Without league standings, we still produce a useful "your week" summary
    by collapsing the leader/user fields to None.
    """
    user_position = None
    leader_name = None
    leader_key_pick = None

    if league_team and league_team.opponent_profiles:
        snapshot = league_team.opponent_profiles[-1] or {}
        entries = snapshot.get("entries", [])
        for entry in entries:
            if entry.get("position") == 1:
                leader_name = entry.get("user_name")
            if entry.get("is_user"):
                user_position = entry.get("position")

    scored = [p for p in user_picks if p.was_correct is not None]
    user_score_pct = None
    if scored:
        user_score_pct = sum(1 for p in scored if p.was_correct) / len(scored) * 100

    return LeaguePostMortem(
        race_label=race_label,
        user_position=user_position,
        leader_name=leader_name,
        leader_key_pick=leader_key_pick,
        pitwallai_score_pct=pitwallai_hit_rate * 100,
        user_score_pct=user_score_pct,
        counterfactual_swing=None,
    )
