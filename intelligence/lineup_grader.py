"""Grade a user-stated lineup (drivers + constructors + chip) against PitWallAI.

Lets a player say "I'm playing Limitless with HAM, LEC, ANT, RUS, VER and
MER, FER" and hear back: each pick's practice-pace standing, the lineup's
projected points, and how it compares to PitWallAI's own top-projected lineup —
so they can test their read against the model's, iteratively.

All numbers are deterministic (same practice-pace projection the PICKS engine
uses). An optional BYO-LLM verdict is added on top, grounded to the stated
drivers so it cannot invent anyone.
"""

from __future__ import annotations

from collections import defaultdict

from intelligence.pick_generator import (
    _constructor_drivers,
    _driver_score,
    _projected_race_points,
)
from intelligence.signal_cache import circuit_key_for_race, load_practice_by_driver
from circuits.profiles import get_circuit_profile
from fantasy.rules import CONSTRUCTOR_PRICES_M
from scheduler.calendar import get_race_weekend, profile_circuit_key

_CHIP_LABEL = {
    "limitless": "LIMITLESS",
    "wildcard": "WILDCARD",
    "no_negative": "NO NEGATIVE",
    "extra_drs": "EXTRA DRS (3x)",
    "final_fix": "FINAL FIX",
    "autopilot": "AUTOPILOT",
}
_CHIP_NOTE = {
    "limitless": "ignores the $100M cap for one race — so the play is pure ceiling: load the fastest cars regardless of price.",
    "wildcard": "unlimited free transfers this race — rebuild fully toward the fastest cars.",
    "no_negative": "negative scores floored at zero — lean into high-variance picks.",
    "extra_drs": "triples one driver's points — put it on your highest-ceiling driver.",
}


def _race_name(race_key: str) -> str:
    wk = get_race_weekend(race_key)
    return wk.display_name if wk else race_key


async def _projection(race_key: str):
    """Return (proj_grid, proj_points fn, con_points fn, signals) for a race."""
    circuit_key = circuit_key_for_race(race_key)
    by_driver = await load_practice_by_driver(circuit_key) if circuit_key else {}
    profile_key = profile_circuit_key(get_race_weekend(race_key).circuit_key) if get_race_weekend(race_key) else circuit_key
    circuit = get_circuit_profile(profile_key) if profile_key else None
    signals = by_driver
    candidates = set(signals)
    if circuit and candidates:
        ranked = sorted(
            candidates,
            key=lambda c: _driver_score(c, circuit=circuit, signals=signals, grid={}),
            reverse=True,
        )
    else:
        ranked = sorted(candidates, key=lambda c: signals[c].pace_satisfaction, reverse=True)
    proj_grid = {code: pos for pos, code in enumerate(ranked, start=1)}

    def proj_points(code: str) -> float:
        return _projected_race_points(proj_grid.get(code.upper()))

    con_drivers = _constructor_drivers(candidates)

    def con_points(con: str) -> float:
        return sum(_projected_race_points(proj_grid.get(d)) for d in con_drivers.get(con.upper(), [])[:2])

    return proj_grid, proj_points, con_points, signals


async def grade_lineup(
    race_key: str,
    drivers: list[str],
    constructors: list[str],
    chip: str | None,
    captain: str | None = None,
) -> str:
    """Build a graded assessment of a stated lineup vs PitWallAI's top picks."""
    drivers = [d.upper() for d in drivers]
    constructors = [c.upper() for c in constructors]
    captain = captain.upper() if captain else None
    proj_grid, proj_points, con_points, signals = await _projection(race_key)
    if not signals:
        return (
            "No practice data loaded yet for this weekend, so I can't grade a "
            "lineup. Try again once FP1/FP2 are in."
        )

    lines: list[str] = [f"🏁 Your {_race_name(race_key)} lineup — graded"]
    if chip:
        note = _CHIP_NOTE.get(chip)
        lines.append(f"🎴 Chip: {_CHIP_LABEL.get(chip, chip.upper())}" + (f" — {note}" if note else ""))
    lines.append("")

    # Drivers: practice standing + projected points.
    lines.append("Drivers (projected race pts on practice pace):")
    driver_total = 0.0
    for d in drivers:
        pos = proj_grid.get(d)
        pts = proj_points(d)
        driver_total += pts
        pos_txt = f"P{pos}" if pos else "—"
        lines.append(f"  {d:<4} {pos_txt:<4} {pts:.0f} pts")
    lines.append(f"  → drivers project {driver_total:.0f} pts")

    # Captain — doubles one driver's points. DRS Boost chip triples instead.
    multiplier = 3 if chip == "extra_drs" else 2
    role = "Triple (DRS Boost)" if multiplier == 3 else "Captain (2x)"
    best_cap = max(drivers, key=proj_points) if drivers else None
    cap_bonus = 0.0
    lines.append("")
    if best_cap is not None:
        chosen = captain if captain in drivers else None
        if chosen:
            cap_bonus = proj_points(chosen) * (multiplier - 1)
            verdict = "✅ optimal" if chosen == best_cap else f"🔁 I'd captain {best_cap} (higher ceiling)"
            lines.append(
                f"🧢 {role}: you picked {chosen} (+{cap_bonus:.0f} bonus) — {verdict}."
            )
        else:
            cap_bonus = proj_points(best_cap) * (multiplier - 1)
            lines.append(
                f"🧢 {role}: captain {best_cap} — highest ceiling "
                f"(P{proj_grid.get(best_cap, '?')}, +{cap_bonus:.0f} bonus)."
            )

    # Constructors.
    con_total = 0.0
    if constructors:
        lines.append("")
        lines.append("Constructors:")
        for c in constructors:
            cp = con_points(c)
            con_total += cp
            lines.append(f"  {c:<4} {cp:.0f} pts")
        lines.append(f"  → constructors project {con_total:.0f} pts")

    total = driver_total + con_total + cap_bonus
    lines.append("")
    lines.append(
        f"📊 Your lineup projects ~{total:.0f} pts on practice pace "
        f"(incl. +{cap_bonus:.0f} captain)."
    )

    # Compare to PitWallAI's top-projected lineup (Limitless = ignore budget).
    top_drivers = sorted(
        (c for c in signals if proj_grid.get(c)),
        key=lambda c: proj_points(c),
        reverse=True,
    )[:5]
    con_scores = {con: con_points(con) for con in CONSTRUCTOR_PRICES_M}
    top_cons = sorted(con_scores, key=lambda c: con_scores[c], reverse=True)[:2]

    lines.append("")
    lines.append("🤖 PitWallAI's top picks on practice pace:")
    lines.append(f"  Drivers: {', '.join(top_drivers)}")
    lines.append(f"  Constructors: {', '.join(top_cons)}")

    d_match = [d for d in drivers if d in top_drivers]
    d_miss = [d for d in drivers if d not in top_drivers]
    lines.append("")
    lines.append(f"✅ You match {len(d_match)}/5 of my driver picks.")
    if d_miss:
        better = [t for t in top_drivers if t not in drivers]
        swap_hint = f" — I'd lean {', '.join(better)} over {', '.join(d_miss)}." if better else ""
        lines.append(f"🔁 Differences: you have {', '.join(d_miss)}{swap_hint}")
    if constructors:
        c_match = [c for c in constructors if c in top_cons]
        lines.append(f"🏭 Constructors: you match {len(c_match)}/2 ({', '.join(top_cons)} are my top pair).")

    return "\n".join(lines)


async def model_top_picks(race_key: str) -> tuple[list[str], list[str], str | None]:
    """PitWallAI's top-5 drivers, top-2 constructors and best captain by practice."""
    proj_grid, proj_points, con_points, signals = await _projection(race_key)
    if not signals:
        return [], [], None
    top_drivers = sorted(
        (c for c in signals if proj_grid.get(c)), key=lambda c: proj_points(c), reverse=True
    )[:5]
    con_scores = {con: con_points(con) for con in CONSTRUCTOR_PRICES_M}
    top_cons = sorted(con_scores, key=lambda c: con_scores[c], reverse=True)[:2]
    return top_drivers, top_cons, (top_drivers[0] if top_drivers else None)


async def score_against_result(
    race_key: str,
    drivers: list[str],
    constructors: list[str],
    chip: str | None,
    captain: str | None,
) -> dict | None:
    """Actual fantasy points for a lineup from the real race result, or None.

    Returns None when the race has not been classified yet (no result).
    """
    from openf1.client import OpenF1Client
    from utils.race_key import parse_race_key

    parsed = parse_race_key(race_key)
    weekend = get_race_weekend(race_key)
    if parsed is None or weekend is None:
        return None
    year, _ = parsed
    circuit = get_circuit_profile(profile_circuit_key(weekend.circuit_key))
    if circuit is None:
        return None
    client = OpenF1Client()
    sk = await client.find_session_key(
        year=year, circuit_short_name=circuit.openf1_circuit_name, session_name="Race"
    )
    if sk is None:
        return None
    rows = await client.get_session_results(sk)
    if not rows:
        return None
    roster = {r.driver_number: (r.name_acronym or "") for r in await client.get_drivers(sk)}
    pos_by_code: dict[str, int | None] = {}
    for r in rows:
        code = roster.get(r.driver_number, "").upper()
        if not code:
            continue
        pos_by_code[code] = None if (r.dnf or r.dns or r.dsq) else r.position

    from fantasy.rules import driver_points_race

    def d_pts(code: str) -> int:
        if code not in pos_by_code:
            return 0
        pos = pos_by_code[code]
        return driver_points_race(pos, classified=pos is not None)

    con_drivers = _constructor_drivers(set(pos_by_code))
    multiplier = 3 if chip == "extra_drs" else 2
    drivers = [d.upper() for d in drivers]
    captain = captain.upper() if captain else (max(drivers, key=d_pts) if drivers else None)

    driver_pts = {d: d_pts(d) for d in drivers}
    cap_bonus = driver_pts.get(captain, 0) * (multiplier - 1) if captain else 0
    con_pts = {
        c.upper(): sum(d_pts(x) for x in con_drivers.get(c.upper(), [])[:2]) for c in constructors
    }
    total = sum(driver_pts.values()) + sum(con_pts.values()) + cap_bonus
    return {
        "total": total,
        "driver_pts": driver_pts,
        "constructor_pts": con_pts,
        "captain": captain,
        "captain_bonus": cap_bonus,
        "positions": pos_by_code,
    }


def perfect_lineup_from_positions(positions: dict[str, int | None]) -> dict:
    """Hindsight-optimal lineup and its points from a race's actual positions."""
    from fantasy.rules import driver_points_race

    pts = {c: driver_points_race(p, classified=p is not None) for c, p in positions.items()}
    top5 = sorted(pts, key=lambda c: pts[c], reverse=True)[:5]
    driver_total = sum(pts[c] for c in top5)
    cap_bonus = max((pts[c] for c in top5), default=0)  # captain the best of the five
    con_drivers = _constructor_drivers(set(positions))
    con_pts = {con: sum(pts.get(d, 0) for d in ds[:2]) for con, ds in con_drivers.items()}
    top_cons = sorted(con_pts, key=lambda c: con_pts[c], reverse=True)[:2]
    con_total = sum(con_pts[c] for c in top_cons)
    return {
        "total": driver_total + con_total + cap_bonus,
        "drivers": top5,
        "constructors": top_cons,
    }


async def grade_lineup_facts(
    race_key: str,
    drivers: list[str],
    constructors: list[str],
    chip: str | None,
    captain: str | None = None,
) -> tuple[str, set[str]]:
    """Compact facts + allowed driver codes for an optional grounded LLM verdict."""
    drivers = [d.upper() for d in drivers]
    proj_grid, proj_points, con_points, signals = await _projection(race_key)
    if not signals:
        return "", set()
    parts = [f"Race: {_race_name(race_key)}."]
    if chip:
        parts.append(f"Chip: {_CHIP_LABEL.get(chip, chip)}.")
    best_cap = max(drivers, key=proj_points) if drivers else None
    if best_cap:
        cap_txt = f"chose {captain.upper()}" if captain else "none chosen"
        parts.append(f"Captain: {cap_txt}; model's best captain is {best_cap}.")
    driver_total = sum(proj_points(d) for d in drivers)
    parts.append(
        "Chosen drivers and their practice-projected race points: "
        + ", ".join(f"{d} P{proj_grid.get(d, '?')} {proj_points(d):.0f}pts" for d in drivers)
        + f" (total {driver_total:.0f})."
    )
    if constructors:
        parts.append(
            "Chosen constructors: "
            + ", ".join(f"{c} {con_points(c):.0f}pts" for c in constructors)
            + "."
        )
    top_drivers = sorted(
        (c for c in signals if proj_grid.get(c)), key=lambda c: proj_points(c), reverse=True
    )[:5]
    parts.append("PitWallAI's top-5 drivers on practice pace: " + ", ".join(top_drivers) + ".")
    return " ".join(parts), set(drivers)
