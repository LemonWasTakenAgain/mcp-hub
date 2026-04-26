"""SolutionPattern model — one row per completed/denied/blocked ticket."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    NUMERIC,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base

VALID_OUTCOMES = {"completed", "denied", "blocked", "needs_human"}


class SolutionPattern(Base):
    __tablename__ = "solution_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    agent_role: Mapped[str] = mapped_column(String(100), nullable=False)
    model_assigned: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mr_iid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mr_pipeline_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    freeze_gaps_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    freeze_gaps_total_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float | None] = mapped_column(NUMERIC(8, 4), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('completed', 'denied', 'blocked', 'needs_human')",
            name="ck_solution_pattern_outcome",
        ),
        Index("idx_solution_patterns_ticket", "ticket_id"),
        Index("idx_solution_patterns_role_outcome", "agent_role", "outcome"),
        Index("idx_solution_patterns_created", "created_at"),
    )
