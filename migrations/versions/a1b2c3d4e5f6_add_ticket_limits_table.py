"""Add ticket_limits audit table for dedupe/rate-limit enforcement

Revision ID: a1b2c3d4e5f6
Revises: 90d54c544c9f
Create Date: 2026-04-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "90d54c544c9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_limits",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_role", sa.String(length=100), nullable=False),
        sa.Column("to_role", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("existing_ticket_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_limits_event_type", "ticket_limits", ["event_type"])
    op.create_index("ix_ticket_limits_from_role", "ticket_limits", ["from_role"])


def downgrade() -> None:
    op.drop_index("ix_ticket_limits_from_role", table_name="ticket_limits")
    op.drop_index("ix_ticket_limits_event_type", table_name="ticket_limits")
    op.drop_table("ticket_limits")
