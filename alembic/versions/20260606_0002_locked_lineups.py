"""Locked lineups — committed player call + model pick per race.

Revision ID: 20260606_0002
Revises: 20260527_0001
Create Date: 2026-06-06

Backs db.models.LockedLineup so LOCK/SCORE persist on Postgres (the local
SQLite simulator gets this table via create_all already).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260606_0002"
down_revision: Union[str, None] = "20260527_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "locked_lineups",
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("race_key", sa.String(length=32), nullable=False),
        sa.Column(
            "drivers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "constructors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("chip", sa.String(length=16), nullable=True),
        sa.Column("captain", sa.String(length=8), nullable=True),
        sa.Column(
            "model_drivers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "model_constructors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("model_captain", sa.String(length=8), nullable=True),
        sa.Column(
            "locked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["phone"], ["subscribers.phone"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("phone", "race_key"),
    )


def downgrade() -> None:
    op.drop_table("locked_lineups")
