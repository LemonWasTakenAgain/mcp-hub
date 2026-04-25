"""Service lock model for cross-agent coordination during maintenance windows."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base

# Locks older than this are considered stale and auto-released by the sweep task
LOCK_AUTO_EXPIRE_HOURS = 2


class ServiceLock(Base):
    __tablename__ = "service_locks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service: Mapped[str] = mapped_column(String(100), index=True)
    holder_role: Mapped[str] = mapped_column(String(100), index=True)
    holder_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    expected_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
