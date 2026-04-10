"""Add mr_canary_runs table for MR pipeline smoke test history

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-04-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mr_canary_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("mr_iid", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('pass', 'timeout', 'error', 'needs_human')",
            name="ck_canary_outcome",
        ),
    )
    op.create_index("ix_mr_canary_runs_project_id", "mr_canary_runs", ["project_id"])
    op.create_index("ix_mr_canary_runs_outcome", "mr_canary_runs", ["outcome"])
    op.create_index("ix_mr_canary_runs_created_at", "mr_canary_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_mr_canary_runs_created_at", table_name="mr_canary_runs")
    op.drop_index("ix_mr_canary_runs_outcome", table_name="mr_canary_runs")
    op.drop_index("ix_mr_canary_runs_project_id", table_name="mr_canary_runs")
    op.drop_table("mr_canary_runs")
