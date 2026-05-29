"""Run Alembic migrations synchronously (called from async init_db)."""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

_ROOT = Path(__file__).resolve().parent.parent


def _sync_database_url() -> str | None:
    raw = os.getenv("DATABASE_URL", "").strip()
    if not raw:
        return None
    url = raw.replace("postgres://", "postgresql://", 1)
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def run_alembic_upgrade() -> None:
    """Apply all pending Alembic revisions. No-op when DATABASE_URL unset."""
    url = _sync_database_url()
    if not url:
        logger.debug("Alembic skipped — DATABASE_URL unset")
        return

    os.environ.setdefault("DATABASE_URL", url)

    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.warning("Alembic not installed — falling back to create_all only")
        return

    ini_path = _ROOT / "alembic.ini"
    if not ini_path.is_file():
        logger.warning("alembic.ini not found — skipping Alembic upgrade")
        return

    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    logger.info("Alembic upgrade complete (head)")
