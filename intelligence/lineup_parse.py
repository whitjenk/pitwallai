"""Backwards-compatible shim — the parser moved to :mod:`core.parse` (brief 006).

The forgiving name/lineup resolution now lives in ``core`` so the Slack app and
the legacy WhatsApp handlers share one implementation. This module re-exports
the public functions so existing imports keep working.
"""

from __future__ import annotations

from core.parse import (
    resolve_captain,
    resolve_chip,
    resolve_constructors,
    resolve_drivers,
)

__all__ = [
    "resolve_captain",
    "resolve_chip",
    "resolve_constructors",
    "resolve_drivers",
]
