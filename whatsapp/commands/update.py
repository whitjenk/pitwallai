"""UPDATE — fix one driver/constructor slot without re-screenshotting.

Examples:
    UPDATE D4 ALB        → driver_4 = ALB
    UPDATE D1 NOR        → driver_1 = NOR
    UPDATE C2 MCL        → constructor_2 = MCL
    UPDATE BUDGET 4.2    → remaining_budget = 4.2
    UPDATE TRANSFERS 2   → transfers_available = 2
"""

from __future__ import annotations

import re

from fantasy.rules import CONSTRUCTOR_PRICES_M, DRIVER_PRICES_M
from intelligence.repository import upsert_fantasy_team_fields

_DRIVER_SLOT_RE = re.compile(r"^D([1-5])$")
_CONSTRUCTOR_SLOT_RE = re.compile(r"^C([12])$")


def _parse(raw_text: str) -> tuple[str, str] | None:
    parts = raw_text.strip().upper().split()
    if len(parts) != 3 or parts[0] != "UPDATE":
        return None
    return parts[1], parts[2]


async def handle_update(phone_number: str, raw_text: str) -> str:
    """Validate one field update; write via existing partial upsert."""
    parsed = _parse(raw_text)
    if parsed is None:
        return (
            "Use: *UPDATE D4 ALB*  ·  *UPDATE C2 MCL*  ·  "
            "*UPDATE BUDGET 4.2*  ·  *UPDATE TRANSFERS 2*"
        )

    slot, value = parsed

    # Driver slot
    if (m := _DRIVER_SLOT_RE.match(slot)) is not None:
        if value not in DRIVER_PRICES_M:
            return f"Unknown driver code *{value}*. Try a 3-letter code like NOR, VER, LEC."
        field = f"driver_{m.group(1)}"
        await upsert_fantasy_team_fields(phone_number, **{field: value})
        return f"✅ Driver {slot} set to *{value}*."

    # Constructor slot
    if (m := _CONSTRUCTOR_SLOT_RE.match(slot)) is not None:
        if value not in CONSTRUCTOR_PRICES_M:
            return f"Unknown constructor code *{value}*. Try MCL, FER, MER…"
        field = f"constructor_{m.group(1)}"
        await upsert_fantasy_team_fields(phone_number, **{field: value})
        return f"✅ Constructor {slot} set to *{value}*."

    # Budget
    if slot == "BUDGET":
        try:
            amount = float(value)
        except ValueError:
            return "Use a number like *UPDATE BUDGET 4.2*."
        if not 0.0 <= amount <= 100.0:
            return "Budget must be between $0M and $100M."
        await upsert_fantasy_team_fields(phone_number, remaining_budget=amount)
        return f"✅ Remaining budget set to *${amount:.1f}M*."

    # Transfers
    if slot == "TRANSFERS":
        try:
            n = int(value)
        except ValueError:
            return "Use an integer like *UPDATE TRANSFERS 2*."
        if not 0 <= n <= 5:
            return "Transfers must be between 0 and 5."
        await upsert_fantasy_team_fields(phone_number, transfers_available=n)
        return f"✅ Transfers available set to *{n}*."

    return (
        "I didn't recognise that slot. Use *D1*–*D5* for drivers, "
        "*C1*/*C2* for constructors, *BUDGET*, or *TRANSFERS*."
    )
