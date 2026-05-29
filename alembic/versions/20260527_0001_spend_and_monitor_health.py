"""Spend ledger + race monitor health columns.

Revision ID: 20260527_0001
Revises:
Create Date: 2026-05-27

Pre-launch baseline migration. Existing deployments that used db/migrate.py
create_all + additive ALTERs can stamp head after this runs once.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260527_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "spend_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("month_key", sa.String(length=7), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("detail", sa.String(length=128), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_spend_events_month_key", "spend_events", ["month_key"])
    op.create_index("ix_spend_events_category", "spend_events", ["category"])
    op.create_index("ix_spend_events_recorded_at", "spend_events", ["recorded_at"])

    op.execute(
        "ALTER TABLE race_monitor_state "
        "ADD COLUMN IF NOT EXISTS consecutive_poll_failures INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE race_monitor_state "
        "ADD COLUMN IF NOT EXISTS data_unavailable BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE race_monitor_state DROP COLUMN IF EXISTS data_unavailable"
    )
    op.execute(
        "ALTER TABLE race_monitor_state DROP COLUMN IF EXISTS consecutive_poll_failures"
    )
    op.drop_index("ix_spend_events_recorded_at", table_name="spend_events")
    op.drop_index("ix_spend_events_category", table_name="spend_events")
    op.drop_index("ix_spend_events_month_key", table_name="spend_events")
    op.drop_table("spend_events")
