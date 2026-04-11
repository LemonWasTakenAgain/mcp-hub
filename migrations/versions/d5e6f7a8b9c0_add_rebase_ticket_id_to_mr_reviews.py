"""Add rebase_ticket_id to mr_reviews

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mr_reviews",
        sa.Column("rebase_ticket_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mr_reviews", "rebase_ticket_id")
