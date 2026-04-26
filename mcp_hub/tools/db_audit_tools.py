"""Database audit tools — cross-table stats, search, and activity summaries."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from mcp_hub.database import async_session
from mcp_hub.models.email import EmailMessage, EmailSyncState
from mcp_hub.models.marketing import MarketingCampaign, MarketingMetric, MarketingProject
from mcp_hub.models.mr_review import MrReview
from mcp_hub.models.ticket import Ticket, TicketComment
from mcp_hub.models.tool_log import ToolLog

logger = logging.getLogger(__name__)

# Tables we expose for audit (read-only)
TABLE_MODELS = {
    "tickets": Ticket,
    "ticket_comments": TicketComment,
    "mr_reviews": MrReview,
    "email_messages": EmailMessage,
    "email_sync_state": EmailSyncState,
    "marketing_projects": MarketingProject,
    "marketing_campaigns": MarketingCampaign,
    "marketing_metrics": MarketingMetric,
    "tool_logs": ToolLog,
}


async def db_stats() -> str:
    """Show row counts and disk usage for all MCP Hub database tables."""
    async with async_session() as session:
        lines = ["# Database Statistics", ""]

        # Row counts per table
        lines.append("## Row Counts")
        total_rows = 0
        for name, model in sorted(TABLE_MODELS.items()):
            count = (await session.execute(select(func.count()).select_from(model))).scalar() or 0
            total_rows += count
            lines.append(f"  {name:<25} {count:>8} rows")

        lines.append(f"  {'TOTAL':<25} {total_rows:>8} rows")

        # Disk usage via pg_total_relation_size
        lines.extend(["", "## Table Sizes"])
        result = await session.execute(
            text(
                "SELECT relname, pg_total_relation_size(relid) as size "
                "FROM pg_catalog.pg_statio_user_tables ORDER BY size DESC"
            )
        )
        for row in result:
            size_mb = row.size / 1024 / 1024
            lines.append(f"  {row.relname:<25} {size_mb:>8.2f} MB")

        # Database total size
        db_size = (
            await session.execute(text("SELECT pg_database_size(current_database())"))
        ).scalar()
        if db_size:
            lines.append(f"\n**Total DB size:** {db_size / 1024 / 1024:.2f} MB")

        return "\n".join(lines)


async def db_recent_activity(hours: int = 24) -> str:
    """Show recent activity across all tables in the last N hours."""
    hours = max(1, min(hours, 720))
    cutoff = datetime.now(tz=UTC) - timedelta(hours=hours)

    async with async_session() as session:
        lines = [f"# Recent Activity (last {hours}h)", ""]

        # Recent tickets
        tickets = (
            (
                await session.execute(
                    select(Ticket)
                    .where(Ticket.updated_at >= cutoff)
                    .order_by(Ticket.updated_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        lines.append(f"## Tickets ({len(tickets)} updated)")
        for t in tickets:
            lines.append(
                f"  #{t.id} [{t.status}] {t.title}\n"
                f"      {t.from_role} -> {t.to_role} | {t.updated_at:%Y-%m-%d %H:%M}"
            )

        # Recent MR reviews
        reviews = (
            (
                await session.execute(
                    select(MrReview)
                    .where(MrReview.updated_at >= cutoff)
                    .order_by(MrReview.updated_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        lines.extend(["", f"## MR Reviews ({len(reviews)} updated)"])
        for r in reviews:
            lines.append(
                f"  PID {r.project_id} !{r.mr_iid} [{r.verdict}] {r.title}\n"
                f"      {r.source_branch} | {r.updated_at:%Y-%m-%d %H:%M}"
            )

        # Recent emails
        emails = (
            (
                await session.execute(
                    select(EmailMessage)
                    .where(EmailMessage.received_at >= cutoff)
                    .order_by(EmailMessage.received_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        lines.extend(["", f"## Emails ({len(emails)} received)"])
        for e in emails:
            flags = ""
            if not e.is_read:
                flags += " [UNREAD]"
            lines.append(
                f"  {e.received_at:%Y-%m-%d %H:%M}{flags} from {e.from_addr}\n      {e.subject}"
            )

        # Recent tool invocations
        logs = (
            (
                await session.execute(
                    select(ToolLog)
                    .where(ToolLog.created_at >= cutoff)
                    .order_by(ToolLog.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        lines.extend(["", f"## Tool Invocations ({len(logs)} recent)"])
        for log in logs:
            dur = f" ({log.duration_ms:.0f}ms)" if log.duration_ms else ""
            lines.append(f"  [{log.status}] {log.tool_name}{dur} | {log.created_at:%H:%M}")

        return "\n".join(lines)


async def db_search(query: str, table: str = "", limit: int = 20) -> str:
    """Full-text search across all text columns in the database.

    Optionally restrict to a specific table name.
    """
    if not query.strip():
        return "Error: query cannot be empty"

    limit = max(1, min(limit, 100))
    pattern = f"%{query}%"

    # Map tables to their searchable text columns
    search_map: dict[str, list[tuple[Any, list[Any]]]] = {
        "tickets": [
            (Ticket, [Ticket.title, Ticket.description, Ticket.result, Ticket.denial_reason]),
        ],
        "ticket_comments": [
            (TicketComment, [TicketComment.content]),
        ],
        "mr_reviews": [
            (MrReview, [MrReview.title, MrReview.reason, MrReview.details, MrReview.source_branch]),
        ],
        "email_messages": [
            (
                EmailMessage,
                [
                    EmailMessage.from_addr,
                    EmailMessage.to_addr,
                    EmailMessage.subject,
                    EmailMessage.preview,
                ],
            ),
        ],
        "marketing_projects": [
            (MarketingProject, [MarketingProject.name, MarketingProject.description]),
        ],
        "marketing_campaigns": [
            (
                MarketingCampaign,
                [
                    MarketingCampaign.name,
                    MarketingCampaign.description,
                    MarketingCampaign.goal,
                ],
            ),
        ],
        "tool_logs": [
            (ToolLog, [ToolLog.tool_name, ToolLog.result_summary]),
        ],
    }

    if table:
        if table not in search_map:
            valid = ", ".join(sorted(search_map.keys()))
            return f"Error: unknown table '{table}'. Valid: {valid}"
        search_map = {table: search_map[table]}

    results = []
    async with async_session() as session:
        for tbl_name, entries in search_map.items():
            for model, columns in entries:
                # Build OR condition across columns
                conditions = []
                for col in columns:
                    conditions.append(col.ilike(pattern))

                from sqlalchemy import or_

                q = select(model).where(or_(*conditions)).limit(limit)
                rows = (await session.execute(q)).scalars().all()

                for row in rows:
                    results.append((tbl_name, row))

    if not results:
        scope = f" in {table}" if table else ""
        return f"No results for '{query}'{scope}"

    lines = [f"Search results for '{query}' ({len(results)} matches):"]
    current_table = ""
    for tbl_name, row in results[:limit]:
        if tbl_name != current_table:
            current_table = tbl_name
            lines.append(f"\n## {tbl_name}")

        if tbl_name == "tickets":
            lines.append(f"  #{row.id} [{row.status}] {row.title}")
        elif tbl_name == "ticket_comments":
            lines.append(f"  Comment #{row.id} by {row.role}: {row.content[:100]}")
        elif tbl_name == "mr_reviews":
            lines.append(f"  PID {row.project_id} !{row.mr_iid} [{row.verdict}] {row.title}")
        elif tbl_name == "email_messages":
            lines.append(f"  {row.received_at:%Y-%m-%d} from {row.from_addr}: {row.subject}")
        elif tbl_name == "marketing_projects":
            lines.append(f"  #{row.id} [{row.status}] {row.name}")
        elif tbl_name == "marketing_campaigns":
            lines.append(f"  #{row.id} [{row.status}] {row.name} ({row.channel})")
        elif tbl_name == "tool_logs":
            lines.append(f"  [{row.status}] {row.tool_name}: {(row.result_summary or '')[:80]}")

    return "\n".join(lines)


async def db_table_detail(table: str, limit: int = 20, offset: int = 0) -> str:
    """Show rows from a specific table with pagination."""
    if table not in TABLE_MODELS:
        valid = ", ".join(sorted(TABLE_MODELS.keys()))
        return f"Error: unknown table '{table}'. Valid: {valid}"

    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    model = TABLE_MODELS[table]

    async with async_session() as session:
        # Get total count
        total = (await session.execute(select(func.count()).select_from(model))).scalar() or 0

        # Get rows (order by primary key desc for most recent first)
        q = select(model).order_by(model.id.desc()).limit(limit).offset(offset)  # type: ignore[attr-defined]  # why: all TABLE_MODELS entries have an id column but Base doesn't declare it
        rows = (await session.execute(q)).scalars().all()

        if not rows:
            return f"No rows in {table} (offset={offset})"

        lines = [
            f"# {table} ({total} total, showing {offset + 1}-{offset + len(rows)})",
            "",
        ]

        for row in rows:
            # Generic row display using column inspection
            cols = {c.name: getattr(row, c.name, None) for c in row.__table__.columns}
            line_parts = []
            for col_name, val in cols.items():
                if val is None:
                    continue
                if isinstance(val, datetime):
                    val = val.strftime("%Y-%m-%d %H:%M")
                elif isinstance(val, str) and len(val) > 100:
                    val = val[:100] + "..."
                line_parts.append(f"**{col_name}:** {val}")
            lines.append("  " + " | ".join(line_parts[:6]))
            if len(line_parts) > 6:
                lines.append("  " + " | ".join(line_parts[6:]))
            lines.append("")

        return "\n".join(lines)
