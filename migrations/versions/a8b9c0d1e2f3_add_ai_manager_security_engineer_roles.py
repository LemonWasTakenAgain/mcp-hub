"""Add AI Manager + Security Engineer to ticket_comments role CHECK constraint

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a8b9c0d1e2f3"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL requires drop + recreate to change a CHECK constraint.
    op.drop_constraint("ck_comment_role", "ticket_comments", type_="check")
    op.create_check_constraint(
        "ck_comment_role",
        "ticket_comments",
        "role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
        "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
        "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev', "
        "'AI Manager', 'Security Engineer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comment_role", "ticket_comments", type_="check")
    op.create_check_constraint(
        "ck_comment_role",
        "ticket_comments",
        "role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
        "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
        "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev')",
    )
