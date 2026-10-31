"""Forgiving parsing of fantasy teams and lineups from free text.

Moved here from the WhatsApp layer (brief 006) so the Slack app and the legacy
WhatsApp handlers share one parser and ``core`` stays the single source of
truth. Resolves driver and constructor names (three-letter codes, surnames,
first names, full names, team nicknames), the chip, the captain, and a full
``/pitwall team`` command.

Pure: no database, no chat platform, no network. The driver-name table lives
here (``DRIVER_FULL_NAMES``) and the set of valid codes comes from
``core.rules``, so nothing in this module imports ``whatsapp`` or
``intelligence``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.rules import (
    BUDGET_CAP_M,
    CONSTRUCTORS_PER_TEAM,
    DRIVERS_PER_TEAM,
)

# Driver code -> full name. The source of truth for name resolution; kept in
# ``core`` so the parser needs no chat-layer import. Mirrors the grid in
# ``whatsapp.message_format._DRIVER_LABELS`` (which is now display-only).
DRIVER_FULL_NAMES: dict[str, str] = {
    "VER": "MAX VERSTAPPEN",
    "NOR": "LANDO NORRIS",
    "LEC": "CHARLES LECLERC",
    "HAM": "LEWIS HAMILTON",
    "PIA": "OSCAR PIASTRI",
    "RUS": "GEORGE RUSSELL",
    "SAI": "CARLOS SAINZ",
    "ALO": "FERNANDO ALONSO",
    "ALB": "ALEXANDER ALBON",
    "GAS": "PIERRE GASLY",
    "OCO": "ESTEBAN OCON",
    "HUL": "NICO HULKENBERG",
    "STR": "LANCE STROLL",
    "LAW": "LIAM LAWSON",
    "LIN": "ARVID LINDBLAD",
    "COL": "FRANCO COLAPINTO",
    "BEA": "OLIVER BEARMAN",
    "ANT": "ANDREA KIMI ANTONELLI",
    "HAD": "ISACK HADJAR",
    "BOR": "GABRIEL BORTOLETO",
    "BOT": "VALTTERI BOTTAS",
    "PER": "SERGIO PEREZ",
}

# Team name / nickname -> fantasy constructor code (longest phrases first so
# "red bull racing" wins over "red bull"). Codes match ``core.rules``.
_CONSTRUCTOR_ALIASES: list[tuple[str, str]] = [
    ("red bull racing", "RBR"), ("red bull", "RBR"), ("redbull", "RBR"),
    ("aston martin", "AM"), ("aston", "AM"),
    ("racing bulls", "RB"), ("kick sauber", "SAU"),
    ("mclaren", "MCL"), ("ferrari", "FER"), ("mercedes", "MER"), ("merc", "MER"),
    ("alpine", "ALP"), ("williams", "WIL"), ("haas", "HAA"),
    ("audi", "SAU"), ("sauber", "SAU"), ("cadillac", "CAD"), ("caddy", "CAD"),
    ("mcl", "MCL"), ("fer", "FER"), ("mer", "MER"), ("rbr", "RBR"), ("alp", "ALP"),
    ("wil", "WIL"), ("haa", "HAA"), ("sau", "SAU"), ("cad", "CAD"), ("amr", "AM"),
    ("rb", "RB"),
]

_CHIP_WORDS: list[tuple[str, str]] = [
    ("limitless", "limitless"), ("wildcard", "wildcard"), ("wild card", "wildcard"),
    ("no negative", "no_negative"), ("nonegative", "no_negative"),
    ("extra drs", "extra_drs"), ("drs boost", "extra_drs"), ("3x", "extra_drs"),
    ("triple captain", "extra_drs"), ("final fix", "final_fix"), ("autopilot", "autopilot"),
]

# Words in a team command that are grammar, not asset names — skipped when
# hunting for unrecognised codes.
_TEAM_STOPWORDS = frozenset(
    {"team", "and", "with", "plus", "captain", "c", "the", "budget", "transfer", "transfers"}
)


def _driver_alias_map() -> dict[str, str]:
    """Build ``{code/first-name/surname -> CODE}`` from the driver table."""
    m: dict[str, str] = {}
    for code, full in DRIVER_FULL_NAMES.items():
        m[code.lower()] = code
        for word in full.lower().split():
            if len(word) >= 3:
                m.setdefault(word, code)  # first name, middle, surname
    return m


def resolve_drivers(text: str) -> list[str]:
    """Driver codes mentioned in the text, in order, de-duplicated."""
    aliases = _driver_alias_map()
    out: list[str] = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        code = aliases.get(word)
        if code and code not in out:
            out.append(code)
    return out


def resolve_constructors(text: str) -> list[str]:
    """Constructor codes mentioned in the text, in order, de-duplicated."""
    low = text.lower()
    found: list[tuple[int, str]] = []
    seen: set[str] = set()
    for alias, code in _CONSTRUCTOR_ALIASES:
        if code in seen:
            continue
        m = re.search(rf"\b{re.escape(alias)}\b", low)
        if m:
            found.append((m.start(), code))
            seen.add(code)
    found.sort()
    return [code for _, code in found]


def resolve_chip(text: str) -> str | None:
    """Canonical chip name mentioned in the text, or ``None``."""
    low = text.lower()
    return next((c for word, c in _CHIP_WORDS if word in low), None)


def resolve_captain(text: str, drivers: list[str]) -> str | None:
    """Captain among the lineup's drivers ('captain lewis', 'triple ham', 'leclerc (c)')."""
    aliases = _driver_alias_map()
    low = text.lower()
    drivers_up = [d.upper() for d in drivers]
    patterns = [
        r"(?:captain|captaining|triple|tripling|\(c\)|skipper)\s+([a-z]{2,})",
        r"\b([a-z]{2,})\s+(?:as\s+)?(?:captain|\(c\)|to\s+captain)",
    ]
    for pat in patterns:
        for name in re.findall(pat, low):
            code = aliases.get(name) or (name.upper() if name.upper() in drivers_up else None)
            if code and code in drivers_up:
                return code
    return None


def extract_lineup(text: str) -> tuple[list[str], list[str], str | None]:
    """Pull driver codes, constructor codes and a chip from free text — by code
    OR by name ('hamilton', 'the antonelli kid', 'ferrari double, limitless')."""
    return resolve_drivers(text), resolve_constructors(text), resolve_chip(text)


def extract_captain(text: str, drivers: list[str]) -> str | None:
    """Find a stated captain among the lineup's drivers, by code or name."""
    return resolve_captain(text, drivers)


# ── /pitwall team ... command ──────────────────────────────────────────────
@dataclass
class ParsedTeam:
    """Result of parsing a ``team ...`` command, with any validation errors.

    ``ok`` is true only when ``errors`` is empty; the Slack handler saves the
    team then, and otherwise replies with ``errors`` joined for the user.
    """

    drivers: list[str] = field(default_factory=list)
    constructors: list[str] = field(default_factory=list)
    budget_m: float | None = None
    transfers: int = 0
    unknown: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _unrecognised_tokens(asset_text: str) -> list[str]:
    """Alpha tokens in the asset portion that resolve to no driver or constructor."""
    low = asset_text.lower()
    for alias, _ in _CONSTRUCTOR_ALIASES:
        low = re.sub(rf"\b{re.escape(alias)}\b", " ", low)
    aliases = _driver_alias_map()
    unknown: list[str] = []
    for word in re.findall(r"[a-z][a-z0-9]*", low):
        if word in aliases or word in _TEAM_STOPWORDS or word in unknown:
            continue
        unknown.append(word.upper())
    return unknown


def parse_team_command(text: str) -> ParsedTeam:
    """Parse ``HAM LEC NOR PIA VER MCL FER budget 2.5 transfers 2``.

    Validates that every code is recognised, that the squad is exactly five
    drivers and two constructors, and that the stated remaining budget sits
    within the ``$0–100M`` cap. Returns a :class:`ParsedTeam`; the caller saves
    it only when ``ok``.
    """
    result = ParsedTeam()

    budget_m = re.search(r"\bbudget\s+(-?\d+(?:\.\d+)?)", text, re.IGNORECASE)
    transfers_m = re.search(r"\btransfers?\s+(-?\d+)", text, re.IGNORECASE)
    if budget_m:
        result.budget_m = float(budget_m.group(1))
    if transfers_m:
        result.transfers = int(transfers_m.group(1))

    # Asset portion = everything before the budget/transfers clauses, so a
    # stray number can't be read as a code.
    cut = len(text)
    for m in (budget_m, transfers_m):
        if m:
            cut = min(cut, m.start())
    asset_text = text[:cut]

    result.drivers = resolve_drivers(asset_text)
    result.constructors = resolve_constructors(asset_text)
    result.unknown = _unrecognised_tokens(asset_text)

    if result.unknown:
        result.errors.append("I don't recognise: " + ", ".join(result.unknown))
    if len(result.drivers) != DRIVERS_PER_TEAM:
        result.errors.append(
            f"Need exactly {DRIVERS_PER_TEAM} drivers (found {len(result.drivers)})."
        )
    if len(result.constructors) != CONSTRUCTORS_PER_TEAM:
        result.errors.append(
            f"Need exactly {CONSTRUCTORS_PER_TEAM} constructors (found {len(result.constructors)})."
        )
    if result.budget_m is None:
        result.errors.append("Tell me your budget, e.g. `budget 2.5`.")
    elif not (0.0 <= result.budget_m <= BUDGET_CAP_M):
        result.errors.append(
            f"Budget ${result.budget_m:.1f}M is outside the $0–{BUDGET_CAP_M:.0f}M cap."
        )
    if result.transfers < 0:
        result.errors.append("Transfers can't be negative.")

    return result
