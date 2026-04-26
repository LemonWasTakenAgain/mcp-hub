"""Improvement (friction log) models for agent feedback tracking."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mcp_hub.models.base import Base

VALID_CATEGORIES = {
    "prompt",
    "code",
    "ux",
    "performance",
    "observability",
    "infrastructure",
    "docs",
}
VALID_SEVERITIES = {"blocker", "major", "minor", "nit"}
VALID_IMPROVEMENT_STATUSES = {"open", "triaged", "accepted", "rejected", "resolved", "duplicate"}

VALID_IMPROVEMENT_TRANSITIONS: dict[str, set[str]] = {
    "open": {"triaged", "accepted", "rejected", "duplicate"},
    "triaged": {"accepted", "rejected", "duplicate"},
    "accepted": {"resolved"},
    "rejected": set(),
    "resolved": set(),
    "duplicate": set(),
}


class Improvement(Base):
    __tablename__ = "improvements"
    __table_args__ = (
        CheckConstraint(
            "category IN ('prompt','code','ux','performance',"
            "'observability','infrastructure','docs')",
            name="ck_improvement_category",
        ),
        CheckConstraint(
            "severity IN ('blocker','major','minor','nit')",
            name="ck_improvement_severity",
        ),
        CheckConstraint(
            "status IN ('open','triaged','accepted','rejected','resolved','duplicate')",
            name="ck_improvement_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_role: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20), default="minor")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    related_ticket_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True
    )
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    comments: Mapped[list["ImprovementComment"]] = relationship(
        back_populates="improvement", order_by="ImprovementComment.created_at"
    )


class ImprovementComment(Base):
    __tablename__ = "improvement_comments"
    __table_args__ = (
        CheckConstraint(
            "role IN ('Dev Manager', 'Infra Planner', 'SaaS Dev 1', "
            "'Stock Matrix Dev', 'Dashboard Dev', 'PR Manager', 'AaaS Dev', "
            "'Marketing Dev', 'DR Engineer', 'Agent Dash Dev', "
            "'AI Manager', 'Security Engineer')",
            name="ck_improvement_comment_role",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    improvement_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("improvements.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    improvement: Mapped["Improvement"] = relationship(back_populates="comments")


__all__ = [
    "VALID_CATEGORIES",
    "VALID_IMPROVEMENT_STATUSES",
    "VALID_IMPROVEMENT_TRANSITIONS",
    "VALID_SEVERITIES",
    "Improvement",
    "ImprovementComment",
]
