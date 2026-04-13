"""Update ck_comment_role: remove Infra Worker, add Agent Dash Dev

Revision ID: 793c360ea968
Revises: f7a8b9c0d1e2
Create Date: 2026-04-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "793c360ea968"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_comment_role", "ticket_comments", type_="check")
    op.create_check_constraint(
        "ck_comment_role",
        "ticket_comments",
        "role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
        "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
        "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comment_role", "ticket_comments", type_="check")
    op.create_check_constraint(
        "ck_comment_role",
        "ticket_comments",
        "role IN ('Dev Manager', 'Infra Planner', 'Infra Worker', 'SaaS Dev 1', "
        "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
        "'Marketing Dev', 'DR Engineer')",
    )
