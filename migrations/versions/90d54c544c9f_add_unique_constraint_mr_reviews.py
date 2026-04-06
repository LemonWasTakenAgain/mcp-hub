"""Add unique constraint on mr_reviews (project_id, mr_iid)

Revision ID: 90d54c544c9f
Revises:
Create Date: 2026-04-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "90d54c544c9f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_review_project_mr", "mr_reviews", ["project_id", "mr_iid"])


def downgrade() -> None:
    op.drop_constraint("uq_review_project_mr", "mr_reviews", type_="unique")
