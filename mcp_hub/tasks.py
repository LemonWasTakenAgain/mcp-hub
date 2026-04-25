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
from mcp_hub.models.mr_review import MrReview, ReviewResetLog
from mcp_hub.models.service_lock import LOCK_AUTO_EXPIRE_HOURS, ServiceLock
from mcp_hub.models.ticket import Ticket, TicketComment

logger = logging.getLogger("mcp_hub.tasks")


_SWEEP_MARKER = "[auto-sweep ticket_id={ticket_id}]"


async def _stale_ticket_sweep() -> None:
    """Flag tickets stuck in_progress for >24h and file a PR Manager triage ticket.

    Dedup: a triage ticket is only created once per stale ticket. The description
    is prefixed with `[auto-sweep ticket_id=N]` so subsequent runs can detect that
    one already exists and skip re-filing.
    """
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

        filed = 0
        for ticket in stale:
            logger.warning(
                "Stale ticket #%d: stuck in_progress since %s", ticket.id, ticket.updated_at
            )

            # Dedup: skip if a triage ticket for this stale ticket was already filed.
            marker = _SWEEP_MARKER.format(ticket_id=ticket.id)
            existing_triage = (
                await session.execute(
                    select(Ticket).where(
                        Ticket.description.like(f"{marker}%"),
                        Ticket.status.notin_(["denied", "archived"]),
                    )
                )
            ).scalar_one_or_none()
            if existing_triage:
                logger.debug(
                    "Stale sweep: triage ticket #%d already exists for ticket #%d, skipping",
                    existing_triage.id,
                    ticket.id,
                )
                continue

            # Create a PR Manager triage ticket (once per stale ticket)
            triage = Ticket(
                title=f"Stale ticket triage: #{ticket.id}",
                description=(
                    f"{marker}\n"
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
            filed += 1

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

        if filed:
            await session.commit()
        logger.info(
            "Stale sweep: %d stale tickets checked, %d triage tickets filed",
            len(stale),
            filed,
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
    """Check non-terminal reviews against GitLab; update state for closed/merged/deleted MRs.

    Uses distinct terminal states:
    - "merged"  — GitLab MR was merged
    - "closed"  — GitLab MR was closed/abandoned or deleted (not merged)
    """
    if not settings.gitlab_token:
        logger.debug("Orphan sweep skipped: no GitLab token configured")
        return

    cutoff = datetime.now(UTC) - timedelta(days=7)
    async with async_session() as session:
        result = await session.execute(
            select(MrReview).where(
                MrReview.verdict.notin_(["merged", "closed"]),
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
                    # "merged" on GitLab → our "merged"; closed/deleted → our "closed"
                    new_verdict = "merged" if gl_state == "merged" else "closed"
                    async with async_session() as session:
                        db_review = await session.get(MrReview, review.id)
                        if db_review and db_review.verdict not in ("merged", "closed"):
                            old_verdict = db_review.verdict
                            db_review.verdict = new_verdict
                            if new_verdict == "merged":
                                db_review.merged_at = datetime.now(UTC)
                            await write_audit_entry(
                                session,
                                "mr_review",
                                db_review.id,
                                old_verdict,
                                new_verdict,
                                changed_by="orphan_sweep",
                                reason=f"GitLab MR state={gl_state}",
                            )
                            await session.commit()
                            logger.info(
                                "Orphan sweep: PID=%d !%d verdict %s→%s (gl=%s)",
                                review.project_id,
                                review.mr_iid,
                                old_verdict,
                                new_verdict,
                                gl_state,
                            )
            except Exception as e:
                logger.warning(
                    "Orphan sweep error for PID=%d !%d: %s", review.project_id, review.mr_iid, e
                )


async def _sha_drift_reset() -> None:
    """Reset verdict to pending when a force-push has changed the MR's commit SHA.

    The dispatcher skips 'approved' MRs unconditionally, so a force-push after
    approval leaves the MR permanently locked out of auto-merge. This task catches
    all non-terminal, non-pending reviews whose stored commit_sha no longer matches
    the live SHA on GitLab and resets them to pending so the dispatcher triggers a
    fresh review within one cycle.
    """
    if not settings.gitlab_token:
        logger.debug("SHA drift reset skipped: no GitLab token configured")
        return

    async with async_session() as session:
        result = await session.execute(
            select(MrReview).where(
                MrReview.verdict.in_(["approved", "rejected", "needs_human"]),
            )
        )
        candidates = result.scalars().all()

    if not candidates:
        return

    headers = {"PRIVATE-TOKEN": settings.gitlab_token}
    gitlab_base = settings.gitlab_url.rstrip("/")

    reset_count = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        for review in candidates:
            try:
                url = (
                    f"{gitlab_base}/api/v4/projects/{review.project_id}"
                    f"/merge_requests/{review.mr_iid}"
                )
                resp = await client.get(url, headers=headers)
                if resp.status_code == 404:
                    continue  # MR deleted — orphan sweep handles this
                if resp.status_code != 200:
                    continue

                data = resp.json()
                if data.get("state", "") in ("merged", "closed"):
                    continue  # Terminal — orphan sweep handles this

                live_sha = data.get("sha", "")
                if not live_sha or live_sha == review.commit_sha:
                    continue  # No drift

                # SHA changed — reset to pending for fresh review
                async with async_session() as session:
                    db_review = await session.get(MrReview, review.id)
                    if db_review is None or db_review.verdict not in (
                        "approved",
                        "rejected",
                        "needs_human",
                    ):
                        continue  # Already reset by a concurrent operation

                    old_verdict = db_review.verdict
                    old_sha = db_review.commit_sha

                    db_review.verdict = "pending"
                    db_review.reason = None
                    db_review.details = None
                    db_review.reviewer_model = None
                    db_review.reviewed_at = None
                    db_review.commit_sha = live_sha
                    # Backdate updated_at so the dispatcher's 5-min "reviewer running"
                    # guard (pending_age < 300) doesn't delay re-review. After a SHA
                    # drift reset there is no reviewer in flight, so the guard doesn't
                    # apply. The dispatcher will pick this up on its next cycle (~1 min).
                    db_review.updated_at = datetime.now(UTC) - timedelta(seconds=600)

                    session.add(
                        ReviewResetLog(
                            review_id=db_review.id,
                            old_verdict=old_verdict,
                            old_commit_sha=old_sha,
                            new_commit_sha=live_sha,
                            reason="sha-drift-reset: force-push detected",
                        )
                    )
                    await write_audit_entry(
                        session,
                        "mr_review",
                        db_review.id,
                        old_verdict,
                        "pending",
                        changed_by="sha_drift_reset",
                        reason=f"sha-drift: {old_sha or 'unknown'}→{live_sha}",
                    )
                    await session.commit()
                    reset_count += 1
                    logger.info(
                        "SHA drift reset: PID=%d !%d verdict %s→pending (sha %s→%s)",
                        review.project_id,
                        review.mr_iid,
                        old_verdict,
                        (old_sha or "")[:8],
                        live_sha[:8],
                    )
            except Exception as e:
                logger.warning(
                    "SHA drift reset error for PID=%d !%d: %s",
                    review.project_id,
                    review.mr_iid,
                    e,
                )

    if reset_count:
        logger.info("SHA drift reset: %d review(s) reset to pending", reset_count)


async def _expire_stale_locks() -> None:
    """Auto-release service locks held longer than LOCK_AUTO_EXPIRE_HOURS.

    Safety net for agents that crash or forget to call service_unlock().
    """
    cutoff = datetime.now(UTC) - timedelta(hours=LOCK_AUTO_EXPIRE_HOURS)
    async with async_session() as session:
        result = await session.execute(
            select(ServiceLock).where(
                ServiceLock.released_at.is_(None),
                ServiceLock.acquired_at < cutoff,
            )
        )
        stale = result.scalars().all()
        if not stale:
            return

        now = datetime.now(UTC)
        for lock in stale:
            lock.released_at = now
            logger.warning(
                "Auto-expired stale service lock #%d: '%s' held by %s since %s",
                lock.id,
                lock.service,
                lock.holder_role,
                lock.acquired_at,
            )
        await session.commit()
        logger.info("Lock expiry sweep: auto-released %d stale lock(s)", len(stale))


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
        asyncio.create_task(
            run_periodic(_sha_drift_reset, interval_seconds=60, name="sha_drift_reset"),
            name="sha_drift_reset",
        ),
        asyncio.create_task(
            run_periodic(_expire_stale_locks, interval_seconds=300, name="expire_stale_locks"),
            name="expire_stale_locks",
        ),
    ]
    return tasks
