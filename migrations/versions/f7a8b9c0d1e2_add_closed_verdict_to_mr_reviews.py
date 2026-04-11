"""Add 'closed' to mr_reviews verdict CHECK constraint

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the existing CHECK constraint and recreate with 'closed' added.
    # PostgreSQL requires drop + recreate to change a CHECK constraint.
    op.drop_constraint("ck_review_verdict", "mr_reviews", type_="check")
    op.create_check_constraint(
        "ck_review_verdict",
        "mr_reviews",
        "verdict IN ('pending', 'approved', 'rejected', 'needs_human', 'merged', 'closed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_review_verdict", "mr_reviews", type_="check")
    op.create_check_constraint(
        "ck_review_verdict",
        "mr_reviews",
        "verdict IN ('pending', 'approved', 'rejected', 'needs_human', 'merged')",
    )
