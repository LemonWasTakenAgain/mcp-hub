"""Audit log for tracking entity state transitions."""

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)  # "ticket" or "mr_review"
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    from_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_status: Mapped[str] = mapped_column(String(50))
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def write_audit_entry(
    session: AsyncSession,
    entity_type: str,
    entity_id: int,
    from_status: str | None,
    to_status: str,
    changed_by: str | None = None,
    reason: str | None = None,
) -> None:
    """Write one audit log row to the session (caller commits)."""
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        reason=reason,
        changed_at=datetime.now(UTC),
    )
    session.add(entry)
