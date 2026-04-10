"""MR canary run model for tracking end-to-end pipeline smoke test results."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base

VALID_OUTCOMES = {"pass", "timeout", "error", "needs_human"}


class MrCanaryRun(Base):
    __tablename__ = "mr_canary_runs"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('pass', 'timeout', 'error', 'needs_human')",
            name="ck_canary_outcome",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    branch: Mapped[str] = mapped_column(String(255))
    mr_iid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), index=True)
    elapsed_seconds: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
