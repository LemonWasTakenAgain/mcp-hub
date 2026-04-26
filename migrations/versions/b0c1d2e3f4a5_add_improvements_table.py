"""Add improvements and improvement_comments tables

Revision ID: b0c1d2e3f4a5
Revises: a8b9c0d1e2f3
Create Date: 2026-04-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | None = "a8b9c0d1e2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "improvements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent_role", sa.String(100), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="minor"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "related_ticket_id",
            sa.Integer(),
            sa.ForeignKey("tickets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("comments_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('prompt','code','ux','performance',"
            "'observability','infrastructure','docs')",
            name="ck_improvement_category",
        ),
        sa.CheckConstraint(
            "severity IN ('blocker','major','minor','nit')",
            name="ck_improvement_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open','triaged','accepted','rejected','resolved','duplicate')",
            name="ck_improvement_status",
        ),
        sa.CheckConstraint(
            "agent_role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
            "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
            "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev', "
            "'AI Manager', 'Security Engineer')",
            name="ck_improvement_agent_role",
        ),
    )
    op.create_index("idx_improvements_status", "improvements", ["status"])
    op.create_index("idx_improvements_category_severity", "improvements", ["category", "severity"])
    op.create_index("idx_improvements_agent_role", "improvements", ["agent_role"])

    op.create_table(
        "improvement_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "improvement_id",
            sa.Integer(),
            sa.ForeignKey("improvements.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
            "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
            "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev', "
            "'AI Manager', 'Security Engineer')",
            name="ck_improvement_comment_role",
        ),
    )
    op.create_index(
        "idx_improvement_comments_improvement", "improvement_comments", ["improvement_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_improvement_comments_improvement", table_name="improvement_comments")
    op.drop_table("improvement_comments")

    op.drop_index("idx_improvements_agent_role", table_name="improvements")
    op.drop_index("idx_improvements_category_severity", table_name="improvements")
    op.drop_index("idx_improvements_status", table_name="improvements")
    op.drop_table("improvements")
