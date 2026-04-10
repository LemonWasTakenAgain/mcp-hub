"""Background maintenance tasks for MCP Hub."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from mcp_hub.config import settings
from mcp_hub.database import async_session
from mcp_hub.models.audit_log import write_audit_entry
from mcp_hub.models.mr_review import MrReview
from mcp_hub.models.ticket import Ticket, TicketComment

logger = logging.getLogger("mcp_hub.tasks")


async def _stale_ticket_sweep() -> None:
    """Flag tickets stuck in_progress for >24h and file a PR Manager ticket."""
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    async with async_session() as session:
        result = await session.execute(
            select(Ticket).where(
                Ticket.status == "in_progress",
                Ticket.updated_at < cutoff,
            )
        )
        stale = result.scalars().all()
        if not stale:
            return

        for ticket in stale:
            logger.warning(
                "Stale ticket #%d: stuck in_progress since %s", ticket.id, ticket.updated_at
            )
            # Create a PR Manager triage ticket
            triage = Ticket(
                title=f"Stale ticket triage: #{ticket.id}",
                description=(
                    f"Ticket #{ticket.id} ('{ticket.title}') has been in_progress since "
                    f"{ticket.updated_at.isoformat()} (>{24}h). "
                    f"Assigned to: {ticket.model_assigned or 'unknown'}. "
                    f"Original: {ticket.to_role}.\n\n"
                    "Please investigate and either complete, reset to queued, or deny."
                ),
                from_role="Dev Manager",
                to_role="PR Manager",
                priority="medium",
                status="queued",
            )
            session.add(triage)

            # Add a comment noting the stale detection
            comment = TicketComment(
                ticket_id=ticket.id,
                role="Dev Manager",
                content=(
                    f"[auto] Ticket stuck in_progress for >24h as of "
                    f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC}. "
                    "Filed PR Manager triage ticket."
                ),
            )
            session.add(comment)

        await session.commit()
        logger.info(
            "Stale sweep: flagged %d tickets, filed %d triage tickets", len(stale), len(stale)
        )


async def _archive_old_tickets() -> None:
    """Archive completed/denied tickets older than 30 days."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    async with async_session() as session:
        result = await session.execute(
            select(Ticket).where(
                Ticket.status.in_(["completed", "denied"]),
                Ticket.updated_at < cutoff,
            )
        )
        old_tickets = result.scalars().all()
        for ticket in old_tickets:
            old_status = ticket.status
            ticket.status = "archived"
            await write_audit_entry(
                session,
                "ticket",
                ticket.id,
                old_status,
                "archived",
                changed_by="archive_sweep",
                reason="auto-archived after 30 days",
            )
            logger.info("Archived ticket #%d (was %s)", ticket.id, old_status)
        if old_tickets:
            await session.commit()
            logger.info("Archive sweep: archived %d tickets", len(old_tickets))


async def _orphan_review_sweep() -> None:
    """Check non-merged reviews against GitLab; update state for closed/deleted MRs."""
    if not settings.gitlab_token:
        logger.debug("Orphan sweep skipped: no GitLab token configured")
        return

    cutoff = datetime.now(UTC) - timedelta(days=7)
    async with async_session() as session:
        result = await session.execute(
            select(MrReview).where(
                MrReview.verdict.notin_(["merged"]),
                MrReview.updated_at < cutoff,
            )
        )
        stale_reviews = result.scalars().all()

    if not stale_reviews:
        return

    headers = {"PRIVATE-TOKEN": settings.gitlab_token}
    gitlab_base = settings.gitlab_url.rstrip("/")

    async with httpx.AsyncClient(timeout=10.0) as client:
        for review in stale_reviews:
            try:
                mr_path = f"projects/{review.project_id}/merge_requests/{review.mr_iid}"
                url = f"{gitlab_base}/api/v4/{mr_path}"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    gl_state = "deleted"
                elif resp.status_code != 200:
                    continue
                else:
                    gl_state = resp.json().get("state", "unknown")

                if gl_state in ("closed", "merged", "deleted"):
                    async with async_session() as session:
                        db_review = await session.get(MrReview, review.id)
                        if db_review and db_review.verdict not in ("merged",):
                            old_verdict = db_review.verdict
                            db_review.verdict = "merged"
                            if gl_state == "merged":
                                db_review.merged_at = datetime.now(UTC)
                            await write_audit_entry(
                                session,
                                "mr_review",
                                db_review.id,
                                old_verdict,
                                "merged",
                                changed_by="orphan_sweep",
                                reason=f"GitLab MR state={gl_state}",
                            )
                            await session.commit()
                            logger.info(
                                "Orphan sweep: PID=%d !%d verdict %s→merged (gl=%s)",
                                review.project_id,
                                review.mr_iid,
                                old_verdict,
                                gl_state,
                            )
            except Exception as e:
                logger.warning(
                    "Orphan sweep error for PID=%d !%d: %s", review.project_id, review.mr_iid, e
                )


async def run_periodic(func, interval_seconds: int, name: str) -> None:
    """Run func periodically on a fixed interval."""
    logger.info("Starting periodic task '%s' every %ds", name, interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await func()
        except Exception as e:
            logger.error("Periodic task '%s' failed: %s", name, e)


def start_background_tasks() -> list[asyncio.Task]:
    """Start all background maintenance tasks. Call from lifespan startup."""
    tasks = [
        asyncio.create_task(
            run_periodic(_stale_ticket_sweep, interval_seconds=3600, name="stale_ticket_sweep"),
            name="stale_ticket_sweep",
        ),
        asyncio.create_task(
            run_periodic(_archive_old_tickets, interval_seconds=86400, name="archive_old_tickets"),
            name="archive_old_tickets",
        ),
        asyncio.create_task(
            run_periodic(_orphan_review_sweep, interval_seconds=86400, name="orphan_review_sweep"),
            name="orphan_review_sweep",
        ),
    ]
    return tasks
