"""MR review models for tracking merge request review status."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base

VALID_VERDICTS = {"pending", "approved", "rejected", "needs_human", "merged"}
VERDICT_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"approved", "rejected", "needs_human"},
    "approved": {"merged"},
    "rejected": {"pending"},  # re-review after author pushes fixes
    "needs_human": {"approved", "rejected", "pending"},  # human decides
    "merged": set(),  # terminal
}


class MrReview(Base):
    __tablename__ = "mr_reviews"
    __table_args__ = (UniqueConstraint("project_id", "mr_iid", name="uq_review_project_mr"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    mr_iid: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    source_branch: Mapped[str] = mapped_column(String(255))
    author_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pipeline_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    verdict: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_model: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lines_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
