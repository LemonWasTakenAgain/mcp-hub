"""Solution pattern tools — record and query per-ticket solution metrics."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from mcp_hub.database import async_session
from mcp_hub.models.solution_pattern import VALID_OUTCOMES, SolutionPattern

__all__ = ["create_pattern", "list_patterns", "aggregate_patterns"]

_GROUP_BY_MAP = {
    "role": "agent_role",
    "model": "model_assigned",
    "outcome": "outcome",
}


async def create_pattern(
    ticket_id: int,
    agent_role: str,
    duration_seconds: int,
    outcome: str,
    model_assigned: str | None = None,
    tool_calls: int = 0,
    unique_tool_calls: int = 0,
    retries: int = 0,
    errors: int = 0,
    mr_iid: int | None = None,
    mr_pipeline_runs: int = 0,
    freeze_gaps_count: int = 0,
    freeze_gaps_total_seconds: int = 0,
    estimated_cost_usd: float | None = None,
    notes: str | None = None,
) -> str:
    """Insert a new SolutionPattern row.

    Returns a confirmation string with the new record ID.
    """
    if outcome not in VALID_OUTCOMES:
        return f"Error: invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"

    async with async_session() as session:
        pattern = SolutionPattern(
            ticket_id=ticket_id,
            agent_role=agent_role,
            model_assigned=model_assigned,
            duration_seconds=duration_seconds,
            tool_calls=tool_calls,
            unique_tool_calls=unique_tool_calls,
            retries=retries,
            errors=errors,
            mr_iid=mr_iid,
            mr_pipeline_runs=mr_pipeline_runs,
            freeze_gaps_count=freeze_gaps_count,
            freeze_gaps_total_seconds=freeze_gaps_total_seconds,
            estimated_cost_usd=estimated_cost_usd,
            outcome=outcome,
            notes=notes,
        )
        session.add(pattern)
        await session.commit()
        await session.refresh(pattern)
        return f"SolutionPattern #{pattern.id} recorded for ticket #{ticket_id}"


async def list_patterns(
    agent_role: str = "",
    outcome: str = "",
    since: str = "",
    limit: int = 50,
) -> str:
    """Query solution_patterns with optional filters.

    since: ISO date string (e.g. "2026-04-20") — filter created_at >= since.
    Max limit: 100.
    """
    limit = max(1, min(limit, 100))

    if outcome and outcome not in VALID_OUTCOMES:
        return f"Error: invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            # Ensure timezone-aware for comparison with tz-aware DB column
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=UTC)
        except ValueError:
            return f"Error: invalid since date '{since}'. Expected ISO format, e.g. 2026-04-20"

    async with async_session() as session:
        query = select(SolutionPattern).order_by(SolutionPattern.created_at.desc())

        if agent_role:
            query = query.where(SolutionPattern.agent_role == agent_role)
        if outcome:
            query = query.where(SolutionPattern.outcome == outcome)
        if since_dt is not None:
            query = query.where(SolutionPattern.created_at >= since_dt)

        query = query.limit(limit)
        rows = (await session.execute(query)).scalars().all()

        if not rows:
            parts = []
            if agent_role:
                parts.append(f"role={agent_role}")
            if outcome:
                parts.append(f"outcome={outcome}")
            if since:
                parts.append(f"since={since}")
            filter_desc = f" ({', '.join(parts)})" if parts else ""
            return f"No solution patterns found{filter_desc}"

        lines = [f"Solution Patterns ({len(rows)} results):"]
        for r in rows:
            model = f" [{r.model_assigned}]" if r.model_assigned else ""
            cost = f" cost=${float(r.estimated_cost_usd):.4f}" if r.estimated_cost_usd else ""
            lines.append(
                f"  #{r.id} ticket={r.ticket_id} [{r.outcome}] {r.agent_role}{model}\n"
                f"      duration={r.duration_seconds}s tools={r.tool_calls}"
                f" retries={r.retries} errors={r.errors}"
                f" pipelines={r.mr_pipeline_runs}{cost}\n"
                f"      {r.created_at:%Y-%m-%d %H:%M}"
            )
            if r.notes:
                lines.append(f"      Notes: {r.notes}")
        return "\n".join(lines)


async def aggregate_patterns(
    group_by: str = "role",
    since: str = "",
) -> str:
    """Aggregate solution patterns by role, model, or outcome.

    group_by: one of "role", "model", "outcome"
    Returns a formatted table with avg/max duration and error rates.
    """
    if group_by not in _GROUP_BY_MAP:
        return f"Error: invalid group_by '{group_by}'. Valid: {', '.join(sorted(_GROUP_BY_MAP))}"

    since_dt: datetime | None = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=UTC)
        except ValueError:
            return f"Error: invalid since date '{since}'. Expected ISO format, e.g. 2026-04-20"

    group_col_name = _GROUP_BY_MAP[group_by]
    group_col = getattr(SolutionPattern, group_col_name)

    async with async_session() as session:
        query = select(
            group_col.label("group_value"),
            func.count().label("count"),
            func.avg(SolutionPattern.duration_seconds).label("avg_duration"),
            func.max(SolutionPattern.duration_seconds).label("max_duration"),
            func.avg(SolutionPattern.tool_calls).label("avg_tool_calls"),
            func.avg(SolutionPattern.errors).label("avg_errors"),
            func.avg(SolutionPattern.mr_pipeline_runs).label("avg_pipeline_runs"),
        ).group_by(group_col)

        if since_dt is not None:
            query = query.where(SolutionPattern.created_at >= since_dt)

        rows = (await session.execute(query)).all()

        if not rows:
            return "No solution patterns found" + (f" (since={since})" if since else "")

        def _safe_rate(errors: float, tools: float) -> float:
            if not tools or tools == 0:
                return 0.0
            return round(errors / tools, 4)

        header = (
            f"{'group':<30} {'count':>6} {'avg_dur':>8} {'max_dur':>8}"
            f" {'avg_tools':>9} {'avg_errors':>10} {'err_rate':>9} {'avg_pipes':>9}"
        )
        sep = "-" * len(header)
        lines = [f"Solution Pattern Aggregates (group_by={group_by}):", header, sep]

        for r in rows:
            grp = str(r.group_value or "(unset)")
            avg_dur = round(float(r.avg_duration or 0), 1)
            max_dur = int(r.max_duration or 0)
            avg_tools = round(float(r.avg_tool_calls or 0), 1)
            avg_errors = round(float(r.avg_errors or 0), 2)
            err_rate = _safe_rate(float(r.avg_errors or 0), float(r.avg_tool_calls or 1))
            avg_pipes = round(float(r.avg_pipeline_runs or 0), 1)
            lines.append(
                f"{grp:<30} {r.count:>6} {avg_dur:>8} {max_dur:>8}"
                f" {avg_tools:>9} {avg_errors:>10} {err_rate:>9} {avg_pipes:>9}"
            )

        return "\n".join(lines)
