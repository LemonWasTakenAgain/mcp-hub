"""Add service_locks table for cross-agent maintenance coordination

Revision ID: 9b8a7c6d5e4f
Revises: 793c360ea968
Create Date: 2026-04-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b8a7c6d5e4f"
down_revision: str | None = "793c360ea968"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_locks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("service", sa.String(length=100), nullable=False),
        sa.Column("holder_role", sa.String(length=100), nullable=False),
        sa.Column("holder_session_id", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_locks_service", "service_locks", ["service"])
    op.create_index("ix_service_locks_holder_role", "service_locks", ["holder_role"])
    op.create_index("ix_service_locks_acquired_at", "service_locks", ["acquired_at"])
    op.create_index("ix_service_locks_released_at", "service_locks", ["released_at"])


def downgrade() -> None:
    op.drop_index("ix_service_locks_released_at", table_name="service_locks")
    op.drop_index("ix_service_locks_acquired_at", table_name="service_locks")
    op.drop_index("ix_service_locks_holder_role", table_name="service_locks")
    op.drop_index("ix_service_locks_service", table_name="service_locks")
    op.drop_table("service_locks")
