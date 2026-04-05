"""Ticket queue tools for cross-agent coordination."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from mcp_hub.database import async_session
from mcp_hub.models.ticket import (
    VALID_PRIORITIES,
    VALID_ROLES,
    VALID_STATUSES,
    VALID_TRANSITIONS,
    Ticket,
    TicketComment,
)


async def create_ticket(
    title: str,
    description: str,
    from_role: str,
    to_role: str,
    priority: str = "medium",
) -> str:
    """Create a new ticket in the queue."""
    if not title.strip():
        return "Error: title cannot be empty"
    if not description.strip():
        return "Error: description cannot be empty"
    if from_role not in VALID_ROLES:
        return f"Error: invalid from_role '{from_role}'. Valid: {', '.join(sorted(VALID_ROLES))}"
    if to_role not in VALID_ROLES:
        return f"Error: invalid to_role '{to_role}'. Valid: {', '.join(sorted(VALID_ROLES))}"
    if priority not in VALID_PRIORITIES:
        return f"Error: invalid priority '{priority}'. Valid: high, medium, low"

    async with async_session() as session:
        ticket = Ticket(
            title=title.strip(),
            description=description.strip(),
            from_role=from_role,
            to_role=to_role,
            priority=priority,
            status="queued",
        )
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        return (
            f"Ticket #{ticket.id} created: {ticket.title}\n"
            f"  Status: queued | Priority: {priority}\n"
            f"  From: {from_role} → To: {to_role}"
        )


async def list_tickets(
    status: str = "",
    from_role: str = "",
    to_role: str = "",
    limit: int = 20,
) -> str:
    """List tickets with optional filters."""
    limit = max(1, min(limit, 100))

    async with async_session() as session:
        query = select(Ticket).order_by(
            # high > medium > low
            Ticket.priority.asc(),
            Ticket.created_at.desc(),
        )

        if status:
            if status not in VALID_STATUSES:
                valid = ", ".join(sorted(VALID_STATUSES))
                return f"Error: invalid status '{status}'. Valid: {valid}"
            query = query.where(Ticket.status == status)
        if from_role:
            query = query.where(Ticket.from_role == from_role)
        if to_role:
            query = query.where(Ticket.to_role == to_role)

        query = query.limit(limit)
        tickets = (await session.execute(query)).scalars().all()

        if not tickets:
            parts = []
            if status:
                parts.append(f"status={status}")
            if from_role:
                parts.append(f"from={from_role}")
            if to_role:
                parts.append(f"to={to_role}")
            filter_desc = f" ({', '.join(parts)})" if parts else ""
            return f"No tickets found{filter_desc}"

        lines = [f"Tickets ({len(tickets)} results):"]
        for t in tickets:
            model = f" [{t.model_assigned}]" if t.model_assigned else ""
            lines.append(
                f"  #{t.id} [{t.status}]{model} {t.title}\n"
                f"      {t.from_role} → {t.to_role} | {t.priority} | {t.created_at:%Y-%m-%d %H:%M}"
            )
        return "\n".join(lines)


async def get_ticket(ticket_id: int) -> str:
    """Get full ticket details including comments."""
    async with async_session() as session:
        result = await session.execute(
            select(Ticket).where(Ticket.id == ticket_id).options(selectinload(Ticket.comments))
        )
        ticket = result.scalar_one_or_none()

        if not ticket:
            return f"Error: ticket #{ticket_id} not found"

        lines = [
            f"# Ticket #{ticket.id}: {ticket.title}",
            "",
            f"**Status:** {ticket.status}",
            f"**Priority:** {ticket.priority}",
            f"**From:** {ticket.from_role}",
            f"**To:** {ticket.to_role}",
            f"**Created:** {ticket.created_at:%Y-%m-%d %H:%M}",
            f"**Updated:** {ticket.updated_at:%Y-%m-%d %H:%M}",
        ]

        if ticket.model_assigned:
            lines.append(f"**Model:** {ticket.model_assigned}")
        if ticket.triage_difficulty:
            lines.append(f"**Difficulty:** {ticket.triage_difficulty}")
        if ticket.triage_reasoning:
            lines.append(f"**Triage:** {ticket.triage_reasoning}")

        lines.extend(["", "## Description", ticket.description])

        if ticket.denial_reason:
            lines.extend(["", "## Denial Reason", ticket.denial_reason])
        if ticket.result:
            lines.extend(["", "## Result", ticket.result])

        if ticket.comments:
            lines.extend(["", "## Comments"])
            for c in ticket.comments:
                lines.append(f"**{c.role}** ({c.created_at:%Y-%m-%d %H:%M}):")
                lines.append(f"  {c.content}")
                lines.append("")

        return "\n".join(lines)


async def update_ticket(
    ticket_id: int,
    status: str = "",
    result: str = "",
    denial_reason: str = "",
) -> str:
    """Update a ticket's status, result, or denial reason."""
    async with async_session() as session:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return f"Error: ticket #{ticket_id} not found"

        updates = []

        if status:
            if status not in VALID_STATUSES:
                valid = ", ".join(sorted(VALID_STATUSES))
                return f"Error: invalid status '{status}'. Valid: {valid}"
            allowed = VALID_TRANSITIONS.get(ticket.status, set())
            if status not in allowed:
                return (
                    f"Error: cannot transition from '{ticket.status}' to '{status}'. "
                    f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal state)'}"
                )
            ticket.status = status
            updates.append(f"status → {status}")

        if result:
            ticket.result = result.strip()
            updates.append("result updated")
        if denial_reason:
            ticket.denial_reason = denial_reason.strip()
            updates.append("denial_reason updated")

        if not updates:
            return "Error: no fields to update (provide status, result, or denial_reason)"

        await session.commit()
        return f"Ticket #{ticket_id} updated: {', '.join(updates)}"


async def add_comment(ticket_id: int, role: str, content: str) -> str:
    """Add a comment to a ticket."""
    if not content.strip():
        return "Error: comment content cannot be empty"

    async with async_session() as session:
        ticket = await session.get(Ticket, ticket_id)
        if not ticket:
            return f"Error: ticket #{ticket_id} not found"

        comment = TicketComment(
            ticket_id=ticket_id,
            role=role,
            content=content.strip(),
        )
        session.add(comment)
        await session.commit()
        return f"Comment added to ticket #{ticket_id} by {role}"


async def list_denied(from_role: str = "", limit: int = 10) -> str:
    """List denied tickets, optionally filtered by creator role."""
    limit = max(1, min(limit, 50))

    async with async_session() as session:
        query = (
            select(Ticket)
            .where(Ticket.status == "denied")
            .order_by(Ticket.updated_at.desc())
            .limit(limit)
        )
        if from_role:
            query = query.where(Ticket.from_role == from_role)

        tickets = (await session.execute(query)).scalars().all()

        if not tickets:
            return "No denied tickets found"

        lines = [f"Denied tickets ({len(tickets)}):"]
        for t in tickets:
            reason = t.denial_reason or "(no reason given)"
            lines.append(
                f"  #{t.id} {t.title}\n"
                f"      {t.from_role} → {t.to_role} | {t.updated_at:%Y-%m-%d %H:%M}\n"
                f"      Reason: {reason}"
            )
        return "\n".join(lines)
