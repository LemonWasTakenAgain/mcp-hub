"""Add data integrity constraints: FK cascade, CHECK constraints, audit log table

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-04-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. TicketComment FK cascade
    op.drop_constraint("ticket_comments_ticket_id_fkey", "ticket_comments", type_="foreignkey")
    op.create_foreign_key(
        "ticket_comments_ticket_id_fkey",
        "ticket_comments",
        "tickets",
        ["ticket_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 2. CHECK constraints on ticket status and priority
    op.create_check_constraint(
        "ck_ticket_status",
        "tickets",
        "status IN ('queued', 'triaged', 'in_progress', 'completed', "
        "'denied', 'blocked', 'archived')",
    )
    op.create_check_constraint(
        "ck_ticket_priority",
        "tickets",
        "priority IN ('high', 'medium', 'low')",
    )

    # 3. CHECK constraint on mr_review verdict
    op.create_check_constraint(
        "ck_review_verdict",
        "mr_reviews",
        "verdict IN ('pending', 'approved', 'rejected', 'needs_human', 'merged')",
    )

    # 4. CHECK constraint on ticket_comment role
    op.create_check_constraint(
        "ck_comment_role",
        "ticket_comments",
        "role IN ('Dev Manager', 'Infra Planner', 'Infra Worker', 'SaaS Dev 1', "
        "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
        "'Marketing Dev', 'DR Engineer')",
    )

    # 5. ReviewResetLog audit table for verdict push-resets
    op.create_table(
        "review_reset_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.Integer(), nullable=False),
        sa.Column("old_verdict", sa.String(length=20), nullable=False),
        sa.Column("old_commit_sha", sa.String(length=40), nullable=True),
        sa.Column("new_commit_sha", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["mr_reviews.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_review_reset_logs_review_id", "review_reset_logs", ["review_id"])


def downgrade() -> None:
    op.drop_index("ix_review_reset_logs_review_id", table_name="review_reset_logs")
    op.drop_table("review_reset_logs")

    op.drop_constraint("ck_comment_role", "ticket_comments", type_="check")
    op.drop_constraint("ck_review_verdict", "mr_reviews", type_="check")
    op.drop_constraint("ck_ticket_priority", "tickets", type_="check")
    op.drop_constraint("ck_ticket_status", "tickets", type_="check")

    op.drop_constraint("ticket_comments_ticket_id_fkey", "ticket_comments", type_="foreignkey")
    op.create_foreign_key(
        "ticket_comments_ticket_id_fkey",
        "ticket_comments",
        "tickets",
        ["ticket_id"],
        ["id"],
    )
