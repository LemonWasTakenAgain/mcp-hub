"""Marketing management models."""

import re
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mcp_hub.models.base import Base

VALID_PROJECT_STATUSES = {"idea", "building", "launched", "growing", "sunset"}
VALID_CHANNELS = {"social", "email", "ads", "content", "seo", "referral", "other"}
VALID_CAMPAIGN_STATUSES = {"planned", "active", "paused", "completed", "cancelled"}


def generate_slug(name: str) -> str:
    """Generate URL-safe slug from name."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class MarketingProject(Base):
    __tablename__ = "marketing_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_prop: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idea")
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gitlab_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    campaigns: Mapped[list["MarketingCampaign"]] = relationship(
        back_populates="project", order_by="MarketingCampaign.created_at.desc()"
    )


class MarketingCampaign(Base):
    __tablename__ = "marketing_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("marketing_projects.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel: Mapped[str] = mapped_column(String(50))
    platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    budget_cents: Mapped[int] = mapped_column(Integer, default=0)
    spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["MarketingProject"] = relationship(back_populates="campaigns")
    metrics: Mapped[list["MarketingMetric"]] = relationship(
        back_populates="campaign", order_by="MarketingMetric.metric_date.desc()"
    )


class MarketingMetric(Base):
    __tablename__ = "marketing_metrics"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "metric_date", "source", name="uq_metric_campaign_date_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("marketing_campaigns.id"), index=True
    )
    metric_date: Mapped[date] = mapped_column(Date)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    conversions: Mapped[int] = mapped_column(Integer, default=0)
    spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    campaign: Mapped["MarketingCampaign"] = relationship(back_populates="metrics")
