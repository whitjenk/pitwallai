"""In-memory RaceContext store keyed by race_key."""

from __future__ import annotations

from orchestrator.race_context import RaceContext

_store: dict[str, RaceContext] = {}


def get_context(race_key: str) -> RaceContext | None:
    """Return the current context for a race weekend."""
    return _store.get(race_key)


def set_context(ctx: RaceContext) -> None:
    """Persist context snapshot for a race weekend."""
    _store[ctx.race_weekend.race_key] = ctx


def clear_context(race_key: str) -> None:
    """Remove context after weekend completes."""
    _store.pop(race_key, None)
