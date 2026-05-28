"""Shared FastAPI runtime for WhatsApp commands and scheduled jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger
from pitwallai.agents.radio_intercept.agent import RadioInterceptAgent
from pitwallai.agents.radio_intercept.config import PitWallSettings
from pitwallai.agents.radio_intercept.vector_store import MockVectorStore

if TYPE_CHECKING:
    from fastapi import FastAPI


@dataclass(frozen=True, slots=True)
class PickRuntime:
    """Dependencies required for on-demand pick generation."""

    agent: RadioInterceptAgent
    vector_store: MockVectorStore
    settings: PitWallSettings


_app: FastAPI | None = None
_lazy_runtime: PickRuntime | None = None


def register_fastapi_app(app: FastAPI) -> None:
    """Register the live app for PICKS and align scheduler job context."""
    global _app
    _app = app
    from scheduler.jobs import RaceJobContext, set_race_job_context

    set_race_job_context(RaceJobContext(app=app))
    logger.debug("WhatsApp app runtime registered")


def _runtime_from_app(app: FastAPI) -> PickRuntime | None:
    agent = getattr(app.state, "agent", None)
    vector_store = getattr(app.state, "vector_store", None)
    settings = getattr(app.state, "settings", None)
    if agent is None or vector_store is None or settings is None:
        return None
    return PickRuntime(agent=agent, vector_store=vector_store, settings=settings)


def _lazy_pick_runtime() -> PickRuntime:
    """Rules-only runtime when the full app has not finished startup."""
    global _lazy_runtime
    if _lazy_runtime is not None:
        return _lazy_runtime
    settings = PitWallSettings.from_env()
    try:
        _lazy_runtime = PickRuntime(
            agent=RadioInterceptAgent(settings=settings),
            vector_store=MockVectorStore(embedding_cache_size=32),
            settings=settings,
        )
    except Exception as exc:
        logger.warning("Lazy PICKS runtime unavailable ({}); picks need full app startup", exc)
        raise
    logger.info("PICKS using lazy rules-only runtime (app not registered)")
    return _lazy_runtime


def get_pick_runtime(*, allow_lazy: bool = True) -> PickRuntime | None:
    """
    Resolve pick-generation dependencies.

    Order: registered FastAPI app → scheduler RaceJobContext → lazy rules runtime.
    """
    if _app is not None:
        runtime = _runtime_from_app(_app)
        if runtime is not None:
            return runtime

    try:
        from scheduler.jobs import _require_ctx

        ctx = _require_ctx()
        runtime = _runtime_from_app(ctx.app)
        if runtime is not None:
            return runtime
    except RuntimeError:
        pass

    if allow_lazy:
        return _lazy_pick_runtime()
    return None


def get_fastapi_app() -> FastAPI | None:
    """Return the registered FastAPI app, if any."""
    if _app is not None:
        return _app
    try:
        from scheduler.jobs import _require_ctx

        return _require_ctx().app
    except RuntimeError:
        return None
