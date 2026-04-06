"""FastAPI application - web dashboard + MCP SSE endpoint + proxy management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_hub.config import settings
from mcp_hub.database import engine, get_session
from mcp_hub.mcp_server import get_registered_tools, get_tool_names, mcp
from mcp_hub.metrics import TOTAL_TOOLS, UPSTREAM_CONNECTED, UPSTREAM_TOOLS, metrics_endpoint
from mcp_hub.models import Base, MrReview, Ticket, ToolLog
from mcp_hub.models.mr_review import VALID_VERDICTS, VERDICT_TRANSITIONS
from mcp_hub.models.ticket import VALID_STATUSES, VALID_TRANSITIONS
from mcp_hub.proxy.env_resolver import resolve_registry
from mcp_hub.proxy.manager import ProxyManager
from mcp_hub.proxy.registry import UpstreamRegistry

logger = logging.getLogger("mcp_hub")

# Resolve template/static paths relative to package, not cwd
_BASE_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _BASE_DIR / "templates"
_STATIC_DIR = _BASE_DIR / "static"

# Global proxy manager instance
proxy_manager: ProxyManager | None = None


def _load_registry() -> UpstreamRegistry:
    """Load upstream registry from config file or defaults."""
    config_path = Path(settings.upstreams_config)
    if not config_path.is_absolute():
        config_path = _BASE_DIR / config_path
    if config_path.exists():
        logger.info("Loading upstream config from %s", config_path)
        registry = UpstreamRegistry.from_yaml(config_path)
    else:
        logger.info("No upstreams.yaml found, using built-in defaults")
        from mcp_hub.proxy.defaults import get_default_registry

        registry = get_default_registry()

    resolve_registry(registry)
    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    global proxy_manager

    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("MCP Hub starting up")

    # Auto-create tables
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables ensured")
    except Exception as e:
        logger.error("Database initialization failed: %s", e)

    # Start proxy manager
    if settings.proxy_enabled:
        registry = _load_registry()
        enabled = registry.get_enabled()
        logger.info(
            "Proxy enabled: %d upstream servers configured, %d enabled",
            len(registry.servers),
            len(enabled),
        )
        proxy_manager = ProxyManager(registry=registry, mcp_server=mcp)
        await proxy_manager.start()
    else:
        logger.info("Proxy disabled (set MH_PROXY_ENABLED=true to enable)")

    yield

    if proxy_manager:
        await proxy_manager.stop()
    await engine.dispose()
    logger.info("MCP Hub shut down")


app = FastAPI(
    title="MCP Hub",
    description="Internal MCP server and AI tools platform",
    version="0.2.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Mount MCP SSE transport at /mcp
mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)
app.add_route("/metrics", metrics_endpoint)


# -- Dashboard Routes --


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    """Main dashboard page."""
    tool_stats = []
    recent_logs = []
    total = 0

    try:
        tool_stats = (
            await session.execute(
                select(
                    ToolLog.tool_name,
                    func.count(ToolLog.id).label("count"),
                    func.avg(ToolLog.duration_ms).label("avg_duration"),
                )
                .group_by(ToolLog.tool_name)
                .order_by(func.count(ToolLog.id).desc())
            )
        ).all()

        recent_logs = (
            (await session.execute(select(ToolLog).order_by(ToolLog.created_at.desc()).limit(20)))
            .scalars()
            .all()
        )

        total = (await session.execute(select(func.count(ToolLog.id)))).scalar() or 0
    except Exception as e:
        logger.error("Dashboard DB query failed: %s", e)

    registered_tools = get_tool_names()
    TOTAL_TOOLS.set(len(registered_tools))
    proxy_status = proxy_manager.get_status() if proxy_manager else None
    if proxy_status:
        for srv in proxy_status.get("servers", []):
            UPSTREAM_CONNECTED.labels(server_name=srv["name"]).set(1 if srv["connected"] else 0)
            UPSTREAM_TOOLS.labels(server_name=srv["name"]).set(srv["tools"])
    local_tools = [t for t in registered_tools if "__" not in t]
    proxied_tools = [t for t in registered_tools if "__" in t]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "tool_stats": tool_stats,
            "recent_logs": recent_logs,
            "total_invocations": total,
            "registered_tools": registered_tools,
            "local_tools": local_tools,
            "proxied_tools": proxied_tools,
            "tool_count": len(registered_tools),
            "proxy_status": proxy_status,
        },
    )


@app.get("/healthz")
async def healthz():
    """Liveness probe — returns 200 if the process is alive."""
    return {"status": "alive"}


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    """Readiness probe — returns 503 only if DB is down. Upstream proxy status is
    reported but does not gate readiness, so core API (tickets, reviews, REST)
    stays reachable even when upstream MCP servers are temporarily disconnected."""
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    tool_names = get_tool_names()
    connected = 0
    total = 0

    if proxy_manager:
        ps = proxy_manager.get_status()
        connected = ps["connected"]
        total = ps["total_servers"]

    proxy_healthy = connected >= total / 2 if total > 0 else True

    result = {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "mcp_tools": len(tool_names),
        "version": "0.2.0",
    }

    if proxy_manager:
        result["proxy"] = {
            "enabled": True,
            "servers_connected": connected,
            "servers_total": total,
            "proxied_tools": proxy_manager.get_status()["total_proxied_tools"],
            "healthy": proxy_healthy,
        }

    return JSONResponse(content=result, status_code=200 if db_ok else 503)


@app.get("/api/tools")
async def list_tools():
    """List all registered MCP tools (local + proxied)."""
    tools = []
    tool_map = proxy_manager.get_tool_map() if proxy_manager else {}
    for name, tool in get_registered_tools().items():
        source = tool_map.get(name, "local")
        tools.append(
            {
                "name": name,
                "description": tool.description,
                "source": source,
            }
        )
    return {"tools": tools, "total": len(tools)}


@app.get("/api/proxy/status")
async def proxy_status_endpoint():
    """Get proxy manager status — all upstream connections."""
    if not proxy_manager:
        return {"enabled": False, "message": "Proxy is disabled"}
    return proxy_manager.get_status()


@app.post("/api/proxy/reconnect/{server_name}")
async def proxy_reconnect(server_name: str):
    """Reconnect to a specific upstream MCP server."""
    if not proxy_manager:
        return {"error": "Proxy is disabled"}
    success = await proxy_manager.reconnect(server_name)
    return {"server": server_name, "reconnected": success}


@app.get("/api/proxy/tools")
async def proxy_tool_map():
    """Get the mapping of proxied tool names to upstream sources."""
    if not proxy_manager:
        return {"enabled": False}
    return {"tool_map": proxy_manager.get_tool_map()}


# -- Ticket Queue API (for dispatcher) --


@app.get("/api/tickets")
async def api_list_tickets(
    status: str = "",
    from_role: str = "",
    to_role: str = "",
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List tickets with optional filters. Used by the ticket dispatcher."""
    query = select(Ticket).order_by(Ticket.priority.asc(), Ticket.created_at.desc())
    if status:
        query = query.where(Ticket.status == status)
    if from_role:
        query = query.where(Ticket.from_role == from_role)
    if to_role:
        query = query.where(Ticket.to_role == to_role)
    query = query.limit(min(limit, 100))

    tickets = (await session.execute(query)).scalars().all()
    return {
        "tickets": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "from_role": t.from_role,
                "to_role": t.to_role,
                "priority": t.priority,
                "status": t.status,
                "model_assigned": t.model_assigned,
                "triage_difficulty": t.triage_difficulty,
                "triage_reasoning": t.triage_reasoning,
                "denial_reason": t.denial_reason,
                "result": t.result,
                "created_at": t.created_at.isoformat(),
                "updated_at": t.updated_at.isoformat(),
            }
            for t in tickets
        ],
        "total": len(tickets),
    }


@app.get("/api/tickets/{ticket_id}")
async def api_get_ticket(ticket_id: int, session: AsyncSession = Depends(get_session)):
    """Get a single ticket by ID."""
    ticket = await session.get(Ticket, ticket_id)
    if not ticket:
        return JSONResponse({"error": f"Ticket #{ticket_id} not found"}, status_code=404)
    return {
        "id": ticket.id,
        "title": ticket.title,
        "description": ticket.description,
        "from_role": ticket.from_role,
        "to_role": ticket.to_role,
        "priority": ticket.priority,
        "status": ticket.status,
        "model_assigned": ticket.model_assigned,
        "triage_difficulty": ticket.triage_difficulty,
        "triage_reasoning": ticket.triage_reasoning,
        "denial_reason": ticket.denial_reason,
        "result": ticket.result,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }


@app.patch("/api/tickets/{ticket_id}")
async def api_update_ticket(
    ticket_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    """Update ticket fields. Used by the dispatcher for triage and status updates."""
    ticket = await session.get(Ticket, ticket_id)
    if not ticket:
        return JSONResponse({"error": f"Ticket #{ticket_id} not found"}, status_code=404)

    body = await request.json()
    updates = []

    if "status" in body:
        new_status = body["status"]
        if new_status not in VALID_STATUSES:
            return JSONResponse({"error": f"Invalid status '{new_status}'"}, status_code=400)
        allowed = VALID_TRANSITIONS.get(ticket.status, set())
        if new_status not in allowed:
            return JSONResponse(
                {"error": f"Cannot transition from '{ticket.status}' to '{new_status}'"},
                status_code=400,
            )
        ticket.status = new_status
        updates.append(f"status={new_status}")

    for field in [
        "model_assigned",
        "triage_difficulty",
        "triage_reasoning",
        "denial_reason",
        "result",
    ]:
        if field in body:
            setattr(ticket, field, body[field])
            updates.append(f"{field} updated")

    if updates:
        await session.commit()

    return {"id": ticket_id, "updated": updates}


# -- MR Review API (for dispatcher) --


@app.get("/api/reviews")
async def api_list_reviews(
    project_id: int = 0,
    verdict: str = "",
    author_role: str = "",
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List MR reviews with optional filters. Used by the review dispatcher."""
    query = select(MrReview).order_by(MrReview.updated_at.desc())
    if project_id:
        query = query.where(MrReview.project_id == project_id)
    if verdict:
        query = query.where(MrReview.verdict == verdict)
    if author_role:
        query = query.where(MrReview.author_role == author_role)
    query = query.limit(min(limit, 100))

    reviews = (await session.execute(query)).scalars().all()
    return {
        "reviews": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "mr_iid": r.mr_iid,
                "title": r.title,
                "source_branch": r.source_branch,
                "author_role": r.author_role,
                "pipeline_status": r.pipeline_status,
                "verdict": r.verdict,
                "reason": r.reason,
                "details": r.details,
                "reviewer_model": r.reviewer_model,
                "lines_changed": r.lines_changed,
                "commit_sha": r.commit_sha,
                "mr_url": r.mr_url,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "merged_at": r.merged_at.isoformat() if r.merged_at else None,
            }
            for r in reviews
        ],
        "total": len(reviews),
    }


@app.get("/api/reviews/{review_id}")
async def api_get_review(review_id: int, session: AsyncSession = Depends(get_session)):
    """Get a single MR review by ID."""
    review = await session.get(MrReview, review_id)
    if not review:
        return JSONResponse({"error": f"Review #{review_id} not found"}, status_code=404)
    return {
        "id": review.id,
        "project_id": review.project_id,
        "mr_iid": review.mr_iid,
        "title": review.title,
        "source_branch": review.source_branch,
        "author_role": review.author_role,
        "pipeline_status": review.pipeline_status,
        "verdict": review.verdict,
        "reason": review.reason,
        "details": review.details,
        "reviewer_model": review.reviewer_model,
        "lines_changed": review.lines_changed,
        "commit_sha": review.commit_sha,
        "mr_url": review.mr_url,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "merged_at": review.merged_at.isoformat() if review.merged_at else None,
    }


@app.post("/api/reviews")
async def api_create_review(request: Request, session: AsyncSession = Depends(get_session)):
    """Create or update an MR review record. Used by the dispatcher when it finds a new MR."""
    body = await request.json()
    required = ["project_id", "mr_iid", "title", "source_branch"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    # Upsert: check if a review already exists for this (project_id, mr_iid)
    existing = (
        await session.execute(
            select(MrReview).where(
                MrReview.project_id == body["project_id"],
                MrReview.mr_iid == body["mr_iid"],
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.title = body["title"]
        existing.source_branch = body["source_branch"]
        if "author_role" in body:
            existing.author_role = body["author_role"]
        if "pipeline_status" in body:
            existing.pipeline_status = body["pipeline_status"]
        if "lines_changed" in body:
            existing.lines_changed = body["lines_changed"]
        if "commit_sha" in body:
            existing.commit_sha = body["commit_sha"]
        if "mr_url" in body:
            existing.mr_url = body["mr_url"]
        await session.commit()
        await session.refresh(existing)
        return {"id": existing.id, "verdict": existing.verdict, "updated": True}

    review = MrReview(
        project_id=body["project_id"],
        mr_iid=body["mr_iid"],
        title=body["title"],
        source_branch=body["source_branch"],
        author_role=body.get("author_role"),
        pipeline_status=body.get("pipeline_status"),
        verdict="pending",
        lines_changed=body.get("lines_changed"),
        commit_sha=body.get("commit_sha"),
        mr_url=body.get("mr_url"),
    )
    session.add(review)
    await session.commit()
    await session.refresh(review)
    return {"id": review.id, "verdict": "pending", "updated": False}


@app.patch("/api/reviews/{review_id}")
async def api_update_review(
    review_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    """Update MR review fields. Used by the dispatcher after sonnet review."""
    review = await session.get(MrReview, review_id)
    if not review:
        return JSONResponse({"error": f"Review #{review_id} not found"}, status_code=404)

    body = await request.json()
    updates = []

    if "verdict" in body:
        new_verdict = body["verdict"]
        if new_verdict not in VALID_VERDICTS:
            return JSONResponse({"error": f"Invalid verdict '{new_verdict}'"}, status_code=400)
        allowed = VERDICT_TRANSITIONS.get(review.verdict, set())
        if new_verdict not in allowed:
            return JSONResponse(
                {"error": f"Cannot transition from '{review.verdict}' to '{new_verdict}'"},
                status_code=400,
            )
        old_verdict = review.verdict
        review.verdict = new_verdict
        updates.append(f"verdict={new_verdict}")

        # Auto-set reviewed_at when transitioning from pending to a decided verdict
        if old_verdict == "pending" and new_verdict != "pending" and "reviewed_at" not in body:
            from datetime import datetime as dt

            review.reviewed_at = dt.utcnow()
            updates.append("reviewed_at auto-set")

        # Auto-set merged_at when transitioning to merged
        if new_verdict == "merged" and "merged_at" not in body:
            from datetime import datetime as dt

            review.merged_at = dt.utcnow()
            updates.append("merged_at auto-set")

    for field in [
        "reason",
        "details",
        "reviewer_model",
        "pipeline_status",
        "commit_sha",
        "lines_changed",
    ]:
        if field in body:
            setattr(review, field, body[field])
            updates.append(f"{field} updated")

    if "reviewed_at" in body:
        from datetime import datetime as dt

        review.reviewed_at = dt.fromisoformat(body["reviewed_at"])
        updates.append("reviewed_at set")
    if "merged_at" in body:
        from datetime import datetime as dt

        review.merged_at = dt.fromisoformat(body["merged_at"])
        updates.append("merged_at set")

    if updates:
        await session.commit()

    return {"id": review_id, "updated": updates}


@app.get("/api/logs")
async def get_logs(
    limit: int = 50, tool_name: str = "", session: AsyncSession = Depends(get_session)
):
    """Get tool invocation logs."""
    query = select(ToolLog).order_by(ToolLog.created_at.desc()).limit(min(limit, 200))
    if tool_name:
        query = query.where(ToolLog.tool_name == tool_name)
    try:
        logs = (await session.execute(query)).scalars().all()
    except Exception as e:
        logger.error("Log query failed: %s", e)
        return {"logs": [], "error": str(e)}
    return {
        "logs": [
            {
                "id": log.id,
                "tool_name": log.tool_name,
                "status": log.status,
                "duration_ms": log.duration_ms,
                "caller": log.caller,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }
