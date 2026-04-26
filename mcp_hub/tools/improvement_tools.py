"""Improvement (friction log) tools for agent feedback tracking.

Agents file improvements when they notice recurring friction: slow tools, awkward flows,
prompt rules that contradict each other, UX surprises, recurring failure patterns.

Blocker-severity improvements auto-create a high-priority ticket to Dev Manager.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from mcp_hub.database import async_session
from mcp_hub.models.improvement import (
    VALID_CATEGORIES,
    VALID_IMPROVEMENT_STATUSES,
    VALID_IMPROVEMENT_TRANSITIONS,
    VALID_SEVERITIES,
    Improvement,
    ImprovementComment,
)
from mcp_hub.models.ticket import VALID_ROLES, Ticket

_DEDUPE_WINDOW_HOURS = 24
_DEDUPE_TITLE_PREFIX_LEN = 20


async def create_improvement(
    agent_role: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    related_ticket_id: int | None = None,
) -> str:
    """Create an improvement record in the friction log.

    Valid categories: prompt, code, ux, performance, observability, infrastructure, docs
    Valid severities: blocker, major, minor, nit
    Blocker severity auto-creates a high-priority ticket to Dev Manager.
    """
    if agent_role not in VALID_ROLES:
        return f"Error: invalid agent_role '{agent_role}'. Valid: {', '.join(sorted(VALID_ROLES))}"
    if category not in VALID_CATEGORIES:
        return f"Error: invalid category '{category}'. Valid: {', '.join(sorted(VALID_CATEGORIES))}"
    if severity not in VALID_SEVERITIES:
        return f"Error: invalid severity '{severity}'. Valid: {', '.join(sorted(VALID_SEVERITIES))}"
    if not title.strip():
        return "Error: title cannot be empty"
    if not description.strip():
        return "Error: description cannot be empty"
    if len(title) > 255:
        return f"Error: title too long ({len(title)} chars, max 255)"
    if len(description) > 8192:
        return f"Error: description too long ({len(description)} chars, max 8192)"

    title = title.strip()
    description = description.strip()
    title_prefix = title[:_DEDUPE_TITLE_PREFIX_LEN]
    now = datetime.now(UTC)
    dedupe_cutoff = now - timedelta(hours=_DEDUPE_WINDOW_HOURS)

    async with async_session() as session:
        # Dedupe check: same agent_role + category where title[:20] matches within 24h
        dup_result = await session.execute(
            select(Improvement).where(
                Improvement.agent_role == agent_role,
                Improvement.category == category,
                Improvement.title.like(f"{title_prefix}%"),
                Improvement.created_at >= dedupe_cutoff,
            )
        )
        dup = dup_result.scalar_one_or_none()
        if dup is not None:
            return (
                f"Improvement #{dup.id} already exists with a similar title "
                f"('{dup.title[:40]}...') filed within the last {_DEDUPE_WINDOW_HOURS}h. "
                f"Consider adding a comment to #{dup.id} instead."
            )

        improvement = Improvement(
            agent_role=agent_role,
            category=category,
            severity=severity,
            title=title,
            description=description,
            related_ticket_id=related_ticket_id,
        )
        session.add(improvement)
        await session.flush()  # get improvement.id before creating the ticket

        if severity == "blocker":
            ticket = Ticket(
                title=f"BLOCKER from {agent_role} improvement #{improvement.id}: {title}",
                description=f"Auto-created from improvement #{improvement.id}.\n\n{description}",
                from_role=agent_role,
                to_role="Dev Manager",
                priority="high",
                status="queued",
            )
            session.add(ticket)
            await session.flush()
            improvement.related_ticket_id = ticket.id
            await session.commit()
            return (
                f"Improvement #{improvement.id} created "
                f"(BLOCKER → Ticket #{ticket.id} auto-created)"
            )

        await session.commit()
        return f"Improvement #{improvement.id} created"


async def list_improvements(
    status: str = "",
    category: str = "",
    severity: str = "",
    agent_role: str = "",
    limit: int = 50,
) -> str:
    """List improvements with optional filters."""
    if status and status not in VALID_IMPROVEMENT_STATUSES:
        valid_statuses = ", ".join(sorted(VALID_IMPROVEMENT_STATUSES))
        return f"Error: invalid status '{status}'. Valid: {valid_statuses}"
    if category and category not in VALID_CATEGORIES:
        return f"Error: invalid category '{category}'. Valid: {', '.join(sorted(VALID_CATEGORIES))}"
    if severity and severity not in VALID_SEVERITIES:
        return f"Error: invalid severity '{severity}'. Valid: {', '.join(sorted(VALID_SEVERITIES))}"

    limit = max(1, min(limit, 100))

    async with async_session() as session:
        query = select(Improvement).order_by(Improvement.created_at.desc())
        if status:
            query = query.where(Improvement.status == status)
        if category:
            query = query.where(Improvement.category == category)
        if severity:
            query = query.where(Improvement.severity == severity)
        if agent_role:
            query = query.where(Improvement.agent_role == agent_role)
        query = query.limit(limit)

        improvements = (await session.execute(query)).scalars().all()

        if not improvements:
            parts = []
            if status:
                parts.append(f"status={status}")
            if category:
                parts.append(f"category={category}")
            if severity:
                parts.append(f"severity={severity}")
            if agent_role:
                parts.append(f"agent_role={agent_role}")
            filter_desc = f" ({', '.join(parts)})" if parts else ""
            return f"No improvements found{filter_desc}"

        lines = [f"Improvements ({len(improvements)} results):"]
        for i in improvements:
            lines.append(
                f"  #{i.id} [{i.status}] [{i.severity}] [{i.category}] {i.title}\n"
                f"      {i.agent_role} | {i.created_at:%Y-%m-%d %H:%M}"
            )
        return "\n".join(lines)


async def get_improvement(improvement_id: int) -> str:
    """Get full improvement details including comments."""
    async with async_session() as session:
        result = await session.execute(
            select(Improvement)
            .where(Improvement.id == improvement_id)
            .options(selectinload(Improvement.comments))
        )
        improvement = result.scalar_one_or_none()

        if not improvement:
            return f"Error: improvement #{improvement_id} not found"

        lines = [
            f"# Improvement #{improvement.id}: {improvement.title}",
            "",
            f"**Status:** {improvement.status}",
            f"**Severity:** {improvement.severity}",
            f"**Category:** {improvement.category}",
            f"**Agent:** {improvement.agent_role}",
            f"**Created:** {improvement.created_at:%Y-%m-%d %H:%M}",
            f"**Updated:** {improvement.updated_at:%Y-%m-%d %H:%M}",
        ]

        if improvement.related_ticket_id:
            lines.append(f"**Related Ticket:** #{improvement.related_ticket_id}")
        if improvement.resolved_at:
            lines.append(f"**Resolved:** {improvement.resolved_at:%Y-%m-%d %H:%M}")

        lines.extend(["", "## Description", improvement.description])

        if improvement.comments:
            lines.extend(["", "## Comments"])
            for c in improvement.comments:
                lines.append(f"**{c.role}** ({c.created_at:%Y-%m-%d %H:%M}):")
                lines.append(f"  {c.content}")
                lines.append("")

        return "\n".join(lines)


async def add_comment(improvement_id: int, role: str, content: str) -> str:
    """Add a comment to an improvement record."""
    if role not in VALID_ROLES:
        return f"Error: invalid role '{role}'. Valid: {', '.join(sorted(VALID_ROLES))}"
    if not content.strip():
        return "Error: comment content cannot be empty"

    async with async_session() as session:
        improvement = await session.get(Improvement, improvement_id)
        if not improvement:
            return f"Error: improvement #{improvement_id} not found"

        comment = ImprovementComment(
            improvement_id=improvement_id,
            role=role,
            content=content.strip(),
        )
        session.add(comment)
        improvement.comments_count += 1
        await session.commit()
        return f"Comment added to improvement #{improvement_id} by {role}"


async def update_improvement(
    improvement_id: int,
    status: str = "",
    severity: str = "",
) -> str:
    """Update improvement status or severity."""
    async with async_session() as session:
        improvement = await session.get(Improvement, improvement_id)
        if not improvement:
            return f"Error: improvement #{improvement_id} not found"

        updates = []

        if status:
            if status not in VALID_IMPROVEMENT_STATUSES:
                return (
                    f"Error: invalid status '{status}'. "
                    f"Valid: {', '.join(sorted(VALID_IMPROVEMENT_STATUSES))}"
                )
            allowed = VALID_IMPROVEMENT_TRANSITIONS.get(improvement.status, set())
            if status not in allowed:
                return (
                    f"Error: cannot transition from '{improvement.status}' to '{status}'. "
                    f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal state)'}"
                )
            improvement.status = status
            if status == "resolved":
                improvement.resolved_at = datetime.now(UTC)
            updates.append(f"status → {status}")

        if severity:
            if severity not in VALID_SEVERITIES:
                return (
                    f"Error: invalid severity '{severity}'. "
                    f"Valid: {', '.join(sorted(VALID_SEVERITIES))}"
                )
            improvement.severity = severity
            updates.append(f"severity → {severity}")

        if not updates:
            return "Error: no fields to update (provide status or severity)"

        await session.commit()
        return f"Improvement #{improvement_id} updated: {', '.join(updates)}"
