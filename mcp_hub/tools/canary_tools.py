"""MR canary tools — query and record MR pipeline smoke test runs.

The canary creates a trivial MR in user-projects/mr-canary (PID=26) every 6 hours
and monitors whether the automated reviewer picks it up and merges it within 10 minutes.
Results are stored here for historical analysis.
"""

from __future__ import annotations

from sqlalchemy import select

from mcp_hub.database import async_session
from mcp_hub.models.canary import VALID_OUTCOMES, MrCanaryRun

__all__ = ["list_canary_runs", "record_canary_run"]


async def list_canary_runs(limit: int = 20, outcome: str = "") -> str:
    """List recent MR canary run results.

    Outcomes: pass, timeout, error, needs_human.
    A 'pass' means the MR was reviewed and merged within 10 minutes.
    A 'timeout' means the MR reviewer did not act within 10 minutes — a ticket was filed.
    """
    limit = max(1, min(limit, 100))

    if outcome and outcome not in VALID_OUTCOMES:
        return f"Error: invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"

    async with async_session() as session:
        query = select(MrCanaryRun).order_by(MrCanaryRun.created_at.desc())
        if outcome:
            query = query.where(MrCanaryRun.outcome == outcome)
        query = query.limit(limit)
        runs = (await session.execute(query)).scalars().all()

    if not runs:
        filter_desc = f" (outcome={outcome})" if outcome else ""
        return f"No canary runs found{filter_desc}"

    lines = [f"MR Canary Runs ({len(runs)} results):"]
    for r in runs:
        mr_ref = f"!{r.mr_iid}" if r.mr_iid else "no-MR"
        mins, secs = divmod(r.elapsed_seconds, 60)
        elapsed = f"{r.elapsed_seconds}s" if mins == 0 else f"{mins}m{secs}s"
        lines.append(
            f"  [{r.outcome.upper():10s}] {r.created_at:%Y-%m-%d %H:%M} "
            f"PID={r.project_id} {mr_ref} {r.branch} ({elapsed})"
        )
        if r.error:
            lines.append(f"    Error: {r.error}")
    return "\n".join(lines)


async def record_canary_run(
    project_id: int,
    branch: str,
    outcome: str,
    elapsed_seconds: int,
    mr_iid: int = 0,
    error: str = "",
) -> str:
    """Record a canary run result. Called by the canary runner script or cron job.

    outcome must be one of: pass, timeout, error, needs_human.
    mr_iid=0 means the MR was never created (use 0, not None, for tool compatibility).
    """
    if outcome not in VALID_OUTCOMES:
        return f"Error: invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"
    if not branch:
        return "Error: branch cannot be empty"

    async with async_session() as session:
        run = MrCanaryRun(
            project_id=project_id,
            branch=branch,
            mr_iid=mr_iid if mr_iid > 0 else None,
            outcome=outcome,
            elapsed_seconds=elapsed_seconds,
            error=error.strip() or None,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)

    mr_ref = f"!{mr_iid}" if mr_iid > 0 else "no-MR"
    return f"Recorded canary run #{run.id}: {outcome} PID={project_id} {mr_ref} {elapsed_seconds}s"
