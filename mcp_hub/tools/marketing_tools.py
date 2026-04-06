"""Marketing management tools for tracking projects, campaigns, and metrics."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from mcp_hub.database import async_session
from mcp_hub.models.marketing import (
    VALID_CAMPAIGN_STATUSES,
    VALID_CHANNELS,
    VALID_PROJECT_STATUSES,
    MarketingCampaign,
    MarketingMetric,
    MarketingProject,
    generate_slug,
)
from mcp_hub.tools._validation import validate_url


def _parse_date(date_str: str) -> date | None:
    """Parse a YYYY-MM-DD date string. Returns None if empty, raises ValueError if invalid."""
    if not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date '{date_str}'. Use YYYY-MM-DD format.")


def _validate_url_optional(url: str) -> str | None:
    """Validate URL if non-empty, return None for empty. Returns validated URL."""
    if not url or not url.strip():
        return None
    return validate_url(url)


async def _unique_slug(session, base_slug: str) -> str:
    """Generate a unique slug, appending -2, -3, ... -10 on collision."""
    for suffix in [""] + [f"-{i}" for i in range(2, 11)]:
        candidate = f"{base_slug}{suffix}" if suffix else base_slug
        existing = await session.execute(
            select(MarketingProject).where(MarketingProject.slug == candidate)
        )
        if existing.scalar_one_or_none() is None:
            return candidate
    return f"{base_slug}-{datetime.now().microsecond}"


# -- Project Tools --


async def create_project(
    name: str,
    description: str = "",
    target_audience: str = "",
    value_prop: str = "",
    status: str = "idea",
    website_url: str = "",
    repo_url: str = "",
    gitlab_project_id: int = 0,
) -> str:
    """Create a new marketing project."""
    if not name.strip():
        return "Error: name cannot be empty"
    if status not in VALID_PROJECT_STATUSES:
        valid = ", ".join(sorted(VALID_PROJECT_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"

    try:
        website = _validate_url_optional(website_url)
    except ValueError as e:
        return f"Error: invalid website_url — {e}"
    try:
        repo = _validate_url_optional(repo_url)
    except ValueError as e:
        return f"Error: invalid repo_url — {e}"

    async with async_session() as session:
        base_slug = generate_slug(name.strip())
        slug = await _unique_slug(session, base_slug)

        project = MarketingProject(
            name=name.strip(),
            slug=slug,
            description=description.strip() or None,
            target_audience=target_audience.strip() or None,
            value_prop=value_prop.strip() or None,
            status=status,
            website_url=website,
            repo_url=repo,
            gitlab_project_id=gitlab_project_id if gitlab_project_id > 0 else None,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return (
            f"Project #{project.id} created: {project.name}\n"
            f"  Slug: {project.slug} | Status: {project.status}"
        )


async def update_project(
    project_id: int,
    name: str = "",
    description: str = "",
    target_audience: str = "",
    value_prop: str = "",
    status: str = "",
    website_url: str = "",
    repo_url: str = "",
    gitlab_project_id: int = 0,
) -> str:
    """Update a marketing project's fields."""
    if status and status not in VALID_PROJECT_STATUSES:
        valid = ", ".join(sorted(VALID_PROJECT_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"

    try:
        website = _validate_url_optional(website_url) if website_url else None
    except ValueError as e:
        return f"Error: invalid website_url — {e}"
    try:
        repo = _validate_url_optional(repo_url) if repo_url else None
    except ValueError as e:
        return f"Error: invalid repo_url — {e}"

    async with async_session() as session:
        project = await session.get(MarketingProject, project_id)
        if not project:
            return f"Error: project #{project_id} not found"

        updates = []

        if name.strip():
            project.name = name.strip()
            updates.append("name")
        if description:
            project.description = description.strip() or None
            updates.append("description")
        if target_audience:
            project.target_audience = target_audience.strip() or None
            updates.append("target_audience")
        if value_prop:
            project.value_prop = value_prop.strip() or None
            updates.append("value_prop")
        if status:
            project.status = status
            updates.append(f"status → {status}")
        if website_url:
            project.website_url = website
            updates.append("website_url")
        if repo_url:
            project.repo_url = repo
            updates.append("repo_url")
        if gitlab_project_id > 0:
            project.gitlab_project_id = gitlab_project_id
            updates.append("gitlab_project_id")

        if not updates:
            return "Error: no fields to update"

        await session.commit()
        return f"Project #{project_id} updated: {', '.join(updates)}"


async def get_project(project_id: int) -> str:
    """Get full details of a marketing project including campaigns."""
    async with async_session() as session:
        result = await session.execute(
            select(MarketingProject)
            .where(MarketingProject.id == project_id)
            .options(selectinload(MarketingProject.campaigns))
        )
        project = result.scalar_one_or_none()

        if not project:
            return f"Error: project #{project_id} not found"

        lines = [
            f"# Project #{project.id}: {project.name}",
            "",
            f"**Slug:** {project.slug}",
            f"**Status:** {project.status}",
            f"**Created:** {project.created_at:%Y-%m-%d}",
        ]
        if project.description:
            lines.extend(["", "## Description", project.description])
        if project.target_audience:
            lines.extend(["", "## Target Audience", project.target_audience])
        if project.value_prop:
            lines.extend(["", "## Value Proposition", project.value_prop])
        if project.website_url:
            lines.append(f"\n**Website:** {project.website_url}")
        if project.repo_url:
            lines.append(f"**Repo:** {project.repo_url}")
        if project.gitlab_project_id:
            lines.append(f"**GitLab Project ID:** {project.gitlab_project_id}")

        if project.campaigns:
            lines.extend(["", f"## Campaigns ({len(project.campaigns)})"])
            for c in project.campaigns:
                lines.append(
                    f"  #{c.id} [{c.status}] {c.name} — {c.channel}"
                    + (f"/{c.platform}" if c.platform else "")
                )
        else:
            lines.extend(["", "## Campaigns", "  (none)"])

        return "\n".join(lines)


async def list_projects(status: str = "") -> str:
    """List marketing projects, optionally filtered by status."""
    if status and status not in VALID_PROJECT_STATUSES:
        valid = ", ".join(sorted(VALID_PROJECT_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"

    async with async_session() as session:
        query = select(MarketingProject).order_by(MarketingProject.created_at.desc())
        if status:
            query = query.where(MarketingProject.status == status)

        projects = (await session.execute(query)).scalars().all()

        if not projects:
            desc = f" with status={status}" if status else ""
            return f"No projects found{desc}"

        lines = [f"Marketing Projects ({len(projects)}):"]
        for p in projects:
            lines.append(f"  #{p.id} [{p.status}] {p.name} (slug: {p.slug})")
        return "\n".join(lines)


# -- Campaign Tools --


async def create_campaign(
    project_id: int,
    name: str,
    channel: str,
    platform: str = "",
    status: str = "planned",
    budget_cents: int = 0,
    goal: str = "",
    source: str = "",
) -> str:
    """Create a campaign under a marketing project."""
    if not name.strip():
        return "Error: name cannot be empty"
    if channel not in VALID_CHANNELS:
        return f"Error: invalid channel '{channel}'. Valid: {', '.join(sorted(VALID_CHANNELS))}"
    if status not in VALID_CAMPAIGN_STATUSES:
        valid = ", ".join(sorted(VALID_CAMPAIGN_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"
    if budget_cents < 0:
        return "Error: budget_cents cannot be negative"

    async with async_session() as session:
        project = await session.get(MarketingProject, project_id)
        if not project:
            return f"Error: project #{project_id} not found"

        campaign = MarketingCampaign(
            project_id=project_id,
            name=name.strip(),
            channel=channel,
            platform=platform.strip() or None,
            status=status,
            budget_cents=budget_cents,
            goal=goal.strip() or None,
            source=source.strip() or None,
        )
        session.add(campaign)
        await session.commit()
        await session.refresh(campaign)
        return (
            f"Campaign #{campaign.id} created: {campaign.name}\n"
            f"  Project: #{project_id} | Channel: {channel} | Status: {status}"
        )


async def update_campaign(
    campaign_id: int,
    name: str = "",
    description: str = "",
    channel: str = "",
    platform: str = "",
    status: str = "",
    budget_cents: int = -1,
    spend_cents: int = -1,
    revenue_cents: int = -1,
    goal: str = "",
    outcome: str = "",
    lessons_learned: str = "",
) -> str:
    """Update a campaign's fields. Use -1 for int fields to leave them unchanged."""
    if channel and channel not in VALID_CHANNELS:
        return f"Error: invalid channel '{channel}'. Valid: {', '.join(sorted(VALID_CHANNELS))}"
    if status and status not in VALID_CAMPAIGN_STATUSES:
        valid = ", ".join(sorted(VALID_CAMPAIGN_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"
    if budget_cents != -1 and budget_cents < 0:
        return "Error: budget_cents cannot be negative"
    if spend_cents != -1 and spend_cents < 0:
        return "Error: spend_cents cannot be negative"
    if revenue_cents != -1 and revenue_cents < 0:
        return "Error: revenue_cents cannot be negative"

    async with async_session() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if not campaign:
            return f"Error: campaign #{campaign_id} not found"

        updates = []

        if name.strip():
            campaign.name = name.strip()
            updates.append("name")
        if description:
            campaign.description = description.strip() or None
            updates.append("description")
        if channel:
            campaign.channel = channel
            updates.append(f"channel → {channel}")
        if platform:
            campaign.platform = platform.strip() or None
            updates.append("platform")
        if status:
            campaign.status = status
            updates.append(f"status → {status}")
        if budget_cents != -1:
            campaign.budget_cents = budget_cents
            updates.append("budget_cents")
        if spend_cents != -1:
            campaign.spend_cents = spend_cents
            updates.append("spend_cents")
        if revenue_cents != -1:
            campaign.revenue_cents = revenue_cents
            updates.append("revenue_cents")
        if goal:
            campaign.goal = goal.strip() or None
            updates.append("goal")
        if outcome:
            campaign.outcome = outcome.strip() or None
            updates.append("outcome")
        if lessons_learned:
            campaign.lessons_learned = lessons_learned.strip() or None
            updates.append("lessons_learned")

        if not updates:
            return "Error: no fields to update"

        await session.commit()

        warning = ""
        if campaign.budget_cents > 0 and campaign.spend_cents > campaign.budget_cents:
            warning = "\nWarning: spend exceeds budget"

        return f"Campaign #{campaign_id} updated: {', '.join(updates)}{warning}"


async def get_campaign(campaign_id: int) -> str:
    """Get full details of a campaign including metrics."""
    async with async_session() as session:
        result = await session.execute(
            select(MarketingCampaign)
            .where(MarketingCampaign.id == campaign_id)
            .options(selectinload(MarketingCampaign.metrics))
        )
        campaign = result.scalar_one_or_none()

        if not campaign:
            return f"Error: campaign #{campaign_id} not found"

        budget_str = f"${campaign.budget_cents / 100:.2f}" if campaign.budget_cents else "none"
        spend_str = f"${campaign.spend_cents / 100:.2f}" if campaign.spend_cents else "$0.00"
        revenue_str = f"${campaign.revenue_cents / 100:.2f}" if campaign.revenue_cents else "$0.00"

        lines = [
            f"# Campaign #{campaign.id}: {campaign.name}",
            "",
            f"**Project ID:** #{campaign.project_id}",
            f"**Channel:** {campaign.channel}"
            + (f"/{campaign.platform}" if campaign.platform else ""),
            f"**Status:** {campaign.status}",
            f"**Budget:** {budget_str} | **Spend:** {spend_str} | **Revenue:** {revenue_str}",
        ]
        if campaign.start_date:
            end = campaign.end_date or "ongoing"
            lines.append(f"**Start:** {campaign.start_date} | **End:** {end}")
        if campaign.goal:
            lines.extend(["", "## Goal", campaign.goal])
        if campaign.outcome:
            lines.extend(["", "## Outcome", campaign.outcome])
        if campaign.lessons_learned:
            lines.extend(["", "## Lessons Learned", campaign.lessons_learned])
        if campaign.source:
            lines.append(f"\n**Source:** {campaign.source}")

        metric_count = len(campaign.metrics)
        if metric_count:
            total_impressions = sum(m.impressions for m in campaign.metrics)
            total_clicks = sum(m.clicks for m in campaign.metrics)
            total_conversions = sum(m.conversions for m in campaign.metrics)
            lines.extend(
                [
                    "",
                    f"## Metrics ({metric_count} entries)",
                    f"  Impressions: {total_impressions:,} | Clicks: {total_clicks:,}"
                    f" | Conversions: {total_conversions:,}",
                ]
            )
        else:
            lines.extend(["", "## Metrics", "  (none)"])

        return "\n".join(lines)


async def list_campaigns(
    project_id: int = 0,
    status: str = "",
    channel: str = "",
) -> str:
    """List campaigns with optional filters."""
    if status and status not in VALID_CAMPAIGN_STATUSES:
        valid = ", ".join(sorted(VALID_CAMPAIGN_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid}"
    if channel and channel not in VALID_CHANNELS:
        return f"Error: invalid channel '{channel}'. Valid: {', '.join(sorted(VALID_CHANNELS))}"

    async with async_session() as session:
        if project_id:
            project = await session.get(MarketingProject, project_id)
            if not project:
                return f"Error: project #{project_id} not found"

        query = select(MarketingCampaign).order_by(MarketingCampaign.created_at.desc())
        if project_id:
            query = query.where(MarketingCampaign.project_id == project_id)
        if status:
            query = query.where(MarketingCampaign.status == status)
        if channel:
            query = query.where(MarketingCampaign.channel == channel)

        campaigns = (await session.execute(query)).scalars().all()

        if not campaigns:
            parts = []
            if project_id:
                parts.append(f"project=#{project_id}")
            if status:
                parts.append(f"status={status}")
            if channel:
                parts.append(f"channel={channel}")
            desc = f" ({', '.join(parts)})" if parts else ""
            return f"No campaigns found{desc}"

        lines = [f"Campaigns ({len(campaigns)}):"]
        for c in campaigns:
            platform_str = f"/{c.platform}" if c.platform else ""
            budget = f"${c.budget_cents / 100:.2f}"
            lines.append(
                f"  #{c.id} [{c.status}] {c.name}\n"
                f"      Project: #{c.project_id} | {c.channel}{platform_str} | budget: {budget}"
            )
        return "\n".join(lines)


# -- Metric Tools --


async def add_metric(
    campaign_id: int,
    metric_date: str,
    impressions: int = 0,
    clicks: int = 0,
    conversions: int = 0,
    spend_cents: int = 0,
    revenue_cents: int = 0,
    source: str = "",
    notes: str = "",
) -> str:
    """Add or upsert a daily metric entry for a campaign."""
    if spend_cents < 0:
        return "Error: spend_cents cannot be negative"
    if revenue_cents < 0:
        return "Error: revenue_cents cannot be negative"

    try:
        parsed_date = _parse_date(metric_date)
    except ValueError as e:
        return f"Error: {e}"

    if parsed_date is None:
        return "Error: metric_date cannot be empty"

    async with async_session() as session:
        campaign = await session.get(MarketingCampaign, campaign_id)
        if not campaign:
            return f"Error: campaign #{campaign_id} not found"

        source_val = source.strip() or None

        # Check for existing metric (upsert)
        existing_result = await session.execute(
            select(MarketingMetric).where(
                MarketingMetric.campaign_id == campaign_id,
                MarketingMetric.metric_date == parsed_date,
                MarketingMetric.source == source_val,
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            existing.impressions = impressions
            existing.clicks = clicks
            existing.conversions = conversions
            existing.spend_cents = spend_cents
            existing.revenue_cents = revenue_cents
            existing.notes = notes.strip() or None
            await session.commit()
            return f"Metric updated for campaign #{campaign_id} on {parsed_date}"

        metric = MarketingMetric(
            campaign_id=campaign_id,
            metric_date=parsed_date,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            spend_cents=spend_cents,
            revenue_cents=revenue_cents,
            source=source_val,
            notes=notes.strip() or None,
        )
        session.add(metric)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # Race condition upsert fallback
            existing_result = await session.execute(
                select(MarketingMetric).where(
                    MarketingMetric.campaign_id == campaign_id,
                    MarketingMetric.metric_date == parsed_date,
                    MarketingMetric.source == source_val,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.impressions = impressions
                existing.clicks = clicks
                existing.conversions = conversions
                existing.spend_cents = spend_cents
                existing.revenue_cents = revenue_cents
                existing.notes = notes.strip() or None
                await session.commit()
                return f"Metric updated for campaign #{campaign_id} on {parsed_date}"
            return "Error: failed to insert metric due to conflict"

        await session.refresh(metric)
        return f"Metric #{metric.id} added for campaign #{campaign_id} on {parsed_date}"


async def query_metrics(
    campaign_id: int = 0,
    start_date: str = "",
    end_date: str = "",
) -> str:
    """Query metrics with optional filters by campaign and date range."""
    try:
        start = _parse_date(start_date)
        end = _parse_date(end_date)
    except ValueError as e:
        return f"Error: {e}"

    async with async_session() as session:
        query = select(MarketingMetric).order_by(
            MarketingMetric.metric_date.desc(), MarketingMetric.campaign_id
        )
        if campaign_id:
            campaign = await session.get(MarketingCampaign, campaign_id)
            if not campaign:
                return f"Error: campaign #{campaign_id} not found"
            query = query.where(MarketingMetric.campaign_id == campaign_id)
        if start:
            query = query.where(MarketingMetric.metric_date >= start)
        if end:
            query = query.where(MarketingMetric.metric_date <= end)

        metrics = (await session.execute(query)).scalars().all()

        if not metrics:
            return "No metrics found"

        total_impressions = sum(m.impressions for m in metrics)
        total_clicks = sum(m.clicks for m in metrics)
        total_conversions = sum(m.conversions for m in metrics)
        total_spend = sum(m.spend_cents for m in metrics)
        total_revenue = sum(m.revenue_cents for m in metrics)

        lines = [
            f"Metrics ({len(metrics)} entries):",
            f"  Totals: {total_impressions:,} imp | {total_clicks:,} clicks"
            f" | {total_conversions:,} conv"
            f" | ${total_spend / 100:.2f} spend | ${total_revenue / 100:.2f} revenue",
            "",
        ]
        for m in metrics:
            src = f" [{m.source}]" if m.source else ""
            lines.append(
                f"  {m.metric_date}{src} — campaign #{m.campaign_id}: "
                f"{m.impressions:,} imp / {m.clicks:,} clicks / {m.conversions} conv"
            )
        return "\n".join(lines)


# -- Dashboard --


async def dashboard() -> str:
    """Show marketing dashboard with project health scores."""
    async with async_session() as session:
        projects = (
            (
                await session.execute(
                    select(MarketingProject)
                    .options(
                        selectinload(MarketingProject.campaigns).selectinload(
                            MarketingCampaign.metrics
                        )
                    )
                    .order_by(MarketingProject.status, MarketingProject.name)
                )
            )
            .scalars()
            .all()
        )

        if not projects:
            return "No marketing projects found. Create one with marketing_project_create."

        today = date.today()
        thirty_days_ago = today.replace(day=max(1, today.day - 30))
        # More robust 30-day calculation
        from datetime import timedelta

        thirty_days_ago = today - timedelta(days=30)

        lines = ["# Marketing Dashboard", ""]

        green_count = yellow_count = red_count = 0

        for project in projects:
            active_campaigns = [c for c in project.campaigns if c.status == "active"]
            has_recent_metric = any(
                any(m.metric_date >= thirty_days_ago for m in c.metrics) for c in project.campaigns
            )
            non_terminal_campaigns = [
                c for c in project.campaigns if c.status not in ("completed", "cancelled")
            ]

            if active_campaigns and has_recent_metric:
                health = "GREEN"
                green_count += 1
            elif non_terminal_campaigns:
                health = "YELLOW"
                yellow_count += 1
            else:
                health = "RED"
                red_count += 1

            total_spend = sum(sum(m.spend_cents for m in c.metrics) for c in project.campaigns)
            total_revenue = sum(sum(m.revenue_cents for m in c.metrics) for c in project.campaigns)
            campaign_count = len(project.campaigns)

            lines.append(f"## [{health}] #{project.id} {project.name} ({project.status})")
            lines.append(
                f"  Campaigns: {campaign_count} | "
                f"Active: {len(active_campaigns)} | "
                f"Spend: ${total_spend / 100:.2f} | "
                f"Revenue: ${total_revenue / 100:.2f}"
            )
            if project.website_url:
                lines.append(f"  {project.website_url}")
            lines.append("")

        lines.append(
            f"Summary: {len(projects)} projects — "
            f"{green_count} green / {yellow_count} yellow / {red_count} red"
        )

        return "\n".join(lines)
