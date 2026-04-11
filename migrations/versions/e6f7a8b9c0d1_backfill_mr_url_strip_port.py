"""Backfill mr_url: strip legacy :31356 port from existing rows

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-04-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_SQL = (
    "UPDATE mr_reviews "
    "SET mr_url = REPLACE(mr_url, 'gitlab.steelcanvas.studio:31356', "
    "'gitlab.steelcanvas.studio') "
    "WHERE mr_url LIKE '%:31356%'"
)


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # No safe way to restore the port to rows that were backfilled — no-op.
    pass
