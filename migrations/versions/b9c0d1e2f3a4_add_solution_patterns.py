"""Add solution_patterns table for per-ticket solution metrics

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solution_patterns",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("agent_role", sa.String(100), nullable=False),
        sa.Column("model_assigned", sa.String(50), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_tool_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mr_iid", sa.Integer(), nullable=True),
        sa.Column("mr_pipeline_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("freeze_gaps_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("freeze_gaps_total_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(8, 4), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_solution_pattern_outcome",
        "solution_patterns",
        "outcome IN ('completed', 'denied', 'blocked', 'needs_human')",
    )
    op.create_index("idx_solution_patterns_ticket", "solution_patterns", ["ticket_id"])
    op.create_index(
        "idx_solution_patterns_role_outcome", "solution_patterns", ["agent_role", "outcome"]
    )
    op.create_index("idx_solution_patterns_created", "solution_patterns", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_solution_patterns_created", "solution_patterns")
    op.drop_index("idx_solution_patterns_role_outcome", "solution_patterns")
    op.drop_index("idx_solution_patterns_ticket", "solution_patterns")
    op.drop_constraint("ck_solution_pattern_outcome", "solution_patterns", type_="check")
    op.drop_table("solution_patterns")
