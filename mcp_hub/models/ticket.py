"""Ticket queue models for cross-agent request tracking."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mcp_hub.models.base import Base

# Valid status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"triaged", "in_progress", "denied", "archived"},
    "triaged": {"in_progress", "denied", "archived"},
    "in_progress": {"completed", "denied", "blocked", "queued"},  # queued = reset on crash
    "completed": {"archived"},
    "denied": {"archived"},
    "blocked": {"queued", "archived"},
    "archived": set(),
}

VALID_STATUSES = set(VALID_TRANSITIONS.keys())
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_ROLES = {
    "Dev Manager",
    "Infra Planner",
    "Infra Worker",
    "SaaS Dev 1",
    "Stock Matrix Dev",
    "Dashboard Dev",
    "PR Manager",
    "AaaS Dev",
    "Marketing Dev",
    "DR Engineer",
}


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    from_role: Mapped[str] = mapped_column(String(100), index=True)
    to_role: Mapped[str] = mapped_column(String(100), index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    model_assigned: Mapped[str | None] = mapped_column(String(50), nullable=True)
    triage_difficulty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    triage_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    comments: Mapped[list["TicketComment"]] = relationship(
        back_populates="ticket", order_by="TicketComment.created_at"
    )


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(Integer, ForeignKey("tickets.id"), index=True)
    role: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket: Mapped["Ticket"] = relationship(back_populates="comments")
