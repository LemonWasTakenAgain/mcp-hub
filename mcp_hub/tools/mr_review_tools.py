"""MR review tools for agents to check merge request status."""

from __future__ import annotations

from sqlalchemy import select

from mcp_hub.database import async_session
from mcp_hub.models.mr_review import VALID_VERDICTS, MrReview

__all__ = ["list_reviews", "get_review", "my_mrs", "claim_mr"]


async def list_reviews(
    project_id: int = 0,
    author_role: str = "",
    verdict: str = "",
    limit: int = 20,
) -> str:
    """List MR reviews with optional filters."""
    limit = max(1, min(limit, 100))

    if verdict and verdict not in VALID_VERDICTS:
        return f"Error: invalid verdict '{verdict}'. Valid: {', '.join(sorted(VALID_VERDICTS))}"

    async with async_session() as session:
        query = select(MrReview).order_by(MrReview.updated_at.desc())

        if project_id:
            query = query.where(MrReview.project_id == project_id)
        if author_role:
            query = query.where(MrReview.author_role == author_role)
        if verdict:
            query = query.where(MrReview.verdict == verdict)

        query = query.limit(limit)
        reviews = (await session.execute(query)).scalars().all()

        if not reviews:
            parts = []
            if project_id:
                parts.append(f"project={project_id}")
            if author_role:
                parts.append(f"author={author_role}")
            if verdict:
                parts.append(f"verdict={verdict}")
            filter_desc = f" ({', '.join(parts)})" if parts else ""
            return f"No MR reviews found{filter_desc}"

        lines = [f"MR Reviews ({len(reviews)} results):"]
        for r in reviews:
            model = f" [{r.reviewer_model}]" if r.reviewer_model else ""
            lines.append(
                f"  PID={r.project_id} !{r.mr_iid} [{r.verdict}]{model} {r.title}\n"
                f"      Branch: {r.source_branch} | Pipeline: {r.pipeline_status or '?'}"
                f" | {r.updated_at:%Y-%m-%d %H:%M}"
            )
            if r.reason:
                lines.append(f"      Reason: {r.reason}")
        return "\n".join(lines)


async def get_review(project_id: int, mr_iid: int) -> str:
    """Get full review details for a specific MR."""
    async with async_session() as session:
        result = await session.execute(
            select(MrReview)
            .where(MrReview.project_id == project_id, MrReview.mr_iid == mr_iid)
            .order_by(MrReview.updated_at.desc())
            .limit(1)
        )
        review = result.scalar_one_or_none()

        if not review:
            return f"No review found for PID={project_id} !{mr_iid}"

        lines = [
            f"# MR Review: PID={review.project_id} !{review.mr_iid}",
            "",
            f"**Title:** {review.title}",
            f"**Branch:** {review.source_branch} → main",
            f"**Verdict:** {review.verdict}",
            f"**Pipeline:** {review.pipeline_status or 'unknown'}",
        ]

        if review.author_role:
            lines.append(f"**Author:** {review.author_role}")
        if review.reviewer_model:
            lines.append(f"**Reviewer:** {review.reviewer_model}")
        if review.lines_changed is not None:
            lines.append(f"**Lines changed:** ~{review.lines_changed}")
        if review.commit_sha:
            lines.append(f"**Commit:** {review.commit_sha[:8]}")
        if review.mr_url:
            lines.append(f"**URL:** {review.mr_url}")

        lines.append(f"**Created:** {review.created_at:%Y-%m-%d %H:%M}")
        lines.append(f"**Updated:** {review.updated_at:%Y-%m-%d %H:%M}")
        if review.reviewed_at:
            lines.append(f"**Reviewed:** {review.reviewed_at:%Y-%m-%d %H:%M}")
        if review.merged_at:
            lines.append(f"**Merged:** {review.merged_at:%Y-%m-%d %H:%M}")

        if review.reason:
            lines.extend(["", "## Reason", review.reason])
        if review.details:
            lines.extend(["", "## Details", review.details])

        return "\n".join(lines)


async def my_mrs(author_role: str) -> str:
    """List all open (non-merged) MR reviews for a specific agent role."""
    async with async_session() as session:
        result = await session.execute(
            select(MrReview)
            .where(
                MrReview.author_role == author_role,
                MrReview.verdict != "merged",
            )
            .order_by(MrReview.updated_at.desc())
            .limit(20)
        )
        reviews = result.scalars().all()

        if not reviews:
            return f"No open MRs for {author_role}"

        lines = [f"Open MRs for {author_role}:"]
        for r in reviews:
            lines.append(
                f"  PID={r.project_id} !{r.mr_iid} [{r.verdict}] {r.title}\n"
                f"      Branch: {r.source_branch} | Pipeline: {r.pipeline_status or '?'}"
            )
            if r.reason:
                lines.append(f"      Reason: {r.reason}")
        return "\n".join(lines)


async def claim_mr(project_id: int, mr_iid: int, author_role: str) -> str:
    """Set author_role on an existing MR review record so mr_review_mine() works."""
    if not author_role.strip():
        return "Error: author_role cannot be empty"

    async with async_session() as session:
        result = await session.execute(
            select(MrReview)
            .where(MrReview.project_id == project_id, MrReview.mr_iid == mr_iid)
            .order_by(MrReview.updated_at.desc())
            .limit(1)
        )
        review = result.scalar_one_or_none()

        if not review:
            return (
                f"No review found for PID={project_id} !{mr_iid}. "
                "The dispatcher may not have created the record yet — retry in ~1 minute."
            )

        review.author_role = author_role.strip()
        await session.commit()
        return (
            f"Claimed PID={project_id} !{mr_iid} for {author_role}. "
            f"Use mr_review_mine(author_role='{author_role}') to track status."
        )
