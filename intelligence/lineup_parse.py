"""Forgiving lineup parsing for messy, conversational WhatsApp messages.

Real users don't type codes — they write "playing limitless with hamilton,
leclerc and the antonelli kid, ferrari double, captain lewis". This resolves
driver/constructor names (surnames, first names, full names, or codes), the
chip, and the captain from free text, preserving the order they were mentioned.
"""

from __future__ import annotations

import re


def _driver_alias_map() -> dict[str, str]:
    from whatsapp.message_format import _DRIVER_LABELS

    m: dict[str, str] = {}
    for code, full in _DRIVER_LABELS.items():
        m[code.lower()] = code
        for word in full.lower().split():
            if len(word) >= 3:
                m.setdefault(word, code)  # first name, middle, surname
    return m


# Team name / nickname -> fantasy constructor code (longest phrases first).
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


_CHIP_WORDS: list[tuple[str, str]] = [
    ("limitless", "limitless"), ("wildcard", "wildcard"), ("wild card", "wildcard"),
    ("no negative", "no_negative"), ("nonegative", "no_negative"),
    ("extra drs", "extra_drs"), ("drs boost", "extra_drs"), ("3x", "extra_drs"),
    ("triple captain", "extra_drs"), ("final fix", "final_fix"), ("autopilot", "autopilot"),
]


def resolve_chip(text: str) -> str | None:
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
