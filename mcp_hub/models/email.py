"""Email models for Stalwart JMAP email metadata cache."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base


class EmailMessage(Base):
    """Cached email metadata synced from Stalwart via JMAP."""

    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jmap_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    mailbox: Mapped[str] = mapped_column(String(255), index=True)
    from_addr: Mapped[str] = mapped_column(String(500), index=True)
    to_addr: Mapped[str] = mapped_column(String(1000))
    cc_addr: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subject: Mapped[str] = mapped_column(String(1000))
    preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    is_read: Mapped[bool] = mapped_column(default=False)
    is_flagged: Mapped[bool] = mapped_column(default=False)
    has_attachment: Mapped[bool] = mapped_column(default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_email_from_date", "from_addr", "received_at"),
        Index("ix_email_subject_search", "subject"),
    )


class EmailSyncState(Base):
    """Tracks JMAP sync cursor per account for incremental sync."""

    __tablename__ = "email_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(255), unique=True)
    query_state: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_sync: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    total_synced: Mapped[int] = mapped_column(Integer, default=0)
