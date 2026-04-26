"""Audit trail tools for investigating ticket and MR review history."""

from __future__ import annotations

from sqlalchemy import select

from mcp_hub.database import async_session
from mcp_hub.models.audit_log import AuditLog


async def ticket_history(ticket_id: int) -> str:
    """Return the audit trail for a ticket."""
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "ticket", AuditLog.entity_id == ticket_id)
            .order_by(AuditLog.changed_at.asc())
        )
        entries = result.scalars().all()

        if not entries:
            return f"No audit history found for ticket #{ticket_id}"

        lines = [f"# Audit trail for ticket #{ticket_id} ({len(entries)} events)"]
        for e in entries:
            transition = f"{e.from_status or '(created)'} → {e.to_status}"
            by = f" by {e.changed_by}" if e.changed_by else ""
            reason = f" ({e.reason})" if e.reason else ""
            lines.append(f"  {e.changed_at:%Y-%m-%d %H:%M:%S UTC}  {transition}{by}{reason}")
        return "\n".join(lines)


async def mr_review_history(project_id: int, mr_iid: int) -> str:
    """Return the audit trail for an MR review."""
    from mcp_hub.models.mr_review import MrReview

    async with async_session() as session:
        # Look up the review record first to get its ID
        result = await session.execute(
            select(MrReview)
            .where(MrReview.project_id == project_id, MrReview.mr_iid == mr_iid)
            .order_by(MrReview.updated_at.desc())
            .limit(1)
        )
        review = result.scalar_one_or_none()

        if not review:
            return f"No review record found for PID={project_id} !{mr_iid}"

        audit_result = await session.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == "mr_review", AuditLog.entity_id == review.id)
            .order_by(AuditLog.changed_at.asc())
        )
        entries = audit_result.scalars().all()

        if not entries:
            return f"No audit history found for PID={project_id} !{mr_iid} (review #{review.id})"

        lines = [f"# Audit trail for PID={project_id} !{mr_iid} ({len(entries)} events)"]
        for e in entries:
            transition = f"{e.from_status or '(created)'} → {e.to_status}"
            by = f" by {e.changed_by}" if e.changed_by else ""
            reason = f" ({e.reason})" if e.reason else ""
            lines.append(f"  {e.changed_at:%Y-%m-%d %H:%M:%S UTC}  {transition}{by}{reason}")
        return "\n".join(lines)
