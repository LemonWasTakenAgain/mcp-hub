"""Tool invocation log model."""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from mcp_hub.models.base import Base


class ToolLog(Base):
    __tablename__ = "tool_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    arguments: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="success")
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    caller: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
