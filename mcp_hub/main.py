"""FastAPI application - web dashboard + MCP SSE endpoint + proxy management."""

from __future__ import annotations

import asyncio
import collections.abc
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from datetime import datetime as dt
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from mcp_hub.config import settings
from mcp_hub.database import async_session, engine, get_session
from mcp_hub.logging_config import configure_logging, instrument_tools, request_id_var
from mcp_hub.mcp_server import get_registered_tools, get_tool_names, mcp
from mcp_hub.metrics import (
    REQUEST_ERRORS,
    REQUEST_LATENCY,
    TOTAL_TOOLS,
    UPSTREAM_CONNECTED,
    UPSTREAM_TOOLS,
    metrics_endpoint,
)
from mcp_hub.models import Base, MrCanaryRun, MrReview, ReviewResetLog, Ticket, ToolLog
from mcp_hub.models.audit_log import write_audit_entry
from mcp_hub.models.idempotency import IdempotencyRecord
from mcp_hub.models.mr_review import VALID_VERDICTS, VERDICT_TRANSITIONS
from mcp_hub.models.solution_pattern import VALID_OUTCOMES as SP_VALID_OUTCOMES
from mcp_hub.models.solution_pattern import SolutionPattern
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


def _add_missing_columns(connection: Any) -> None:
    """Detect columns in ORM models missing from the DB and add them.

    create_all only creates new tables — it won't ALTER existing ones.
    This runs DDL for any nullable columns the model defines but the DB lacks.
    """
    inspector = sa_inspect(connection)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        db_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in db_columns:
                continue
            col_type = col.type.compile(connection.engine.dialect)
            stmt = f'ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
            connection.execute(text(stmt))
            logger.info("Added missing column %s.%s (%s)", table.name, col.name, col_type)


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
async def lifespan(app: FastAPI) -> collections.abc.AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    global proxy_manager

    configure_logging(settings.debug)
    logger.info("MCP Hub starting up", extra={"event": "startup", "debug": settings.debug})

    # Warn about missing critical env vars
    if not settings.gitlab_token:
        logger.warning("MH_GITLAB_TOKEN not set — GitLab tools will fail")
    if settings.database_url == "postgresql+asyncpg://mcphub:mcphub@localhost:5432/mcphub":
        logger.warning("MH_DATABASE_URL is using default — ensure this is intentional")

    # Auto-create tables + add missing columns
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_add_missing_columns)
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

    # Start background maintenance tasks
    from mcp_hub.tasks import start_background_tasks

    _bg_tasks: list[asyncio.Task[None]] = start_background_tasks()
    logger.info("Started %d background maintenance tasks", len(_bg_tasks))

    # Instrument all registered tools (local + proxied) with structured logging
    instrument_tools(mcp)

    yield

    # Cancel background tasks
    for t in _bg_tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

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


_CallNext = collections.abc.Callable[[Request], collections.abc.Awaitable[Response]]


@app.middleware("http")
async def security_and_metrics(request: Request, call_next: _CallNext) -> Response:
    """Add security headers and track request metrics."""
    start = time.monotonic()
    response = await call_next(request)
    duration = time.monotonic() - start

    # Security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not settings.debug:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    # Request metrics
    endpoint = request.url.path
    status = str(response.status_code)
    REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint, status=status).observe(
        duration
    )
    if response.status_code >= 400:
        REQUEST_ERRORS.labels(method=request.method, endpoint=endpoint, status=status).inc()

    return response


@app.middleware("http")
async def idempotency_middleware(request: Request, call_next: _CallNext) -> Response:
    """Replay cached response for duplicate PATCH/POST with Idempotency-Key header."""
    idem_key = request.headers.get("Idempotency-Key", "").strip()
    path = request.url.path
    method = request.method

    # Only apply to mutation endpoints
    is_mutation = method in ("PATCH", "POST") and (
        path.startswith("/api/tickets") or path.startswith("/api/reviews")
    )

    if not idem_key or not is_mutation:
        return await call_next(request)

    # Check cache
    async with async_session() as session:
        existing = await session.get(IdempotencyRecord, idem_key)
        if existing:
            return JSONResponse(content=json.loads(existing.response_json), status_code=200)

    # Process request
    response = await call_next(request)

    # Cache the response if successful (2xx)
    if 200 <= response.status_code < 300:
        body_bytes = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]  # why: FastAPI middleware call_next returns a _StreamingResponse with body_iterator, not typed in starlette stubs
            body_bytes += chunk
        try:
            body_dict = json.loads(body_bytes)
        except Exception:
            body_dict = {}
        async with async_session() as session:
            # Cleanup old keys (>24h) opportunistically
            cutoff = dt.now(UTC) - timedelta(hours=24)
            await session.execute(
                sa_delete(IdempotencyRecord).where(IdempotencyRecord.created_at < cutoff)
            )
            record = IdempotencyRecord(key=idem_key, response_json=json.dumps(body_dict))
            session.add(record)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
        return JSONResponse(content=body_dict, status_code=response.status_code)

    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: _CallNext) -> Response:
    """Assign a UUID request_id per request; log HTTP request/response as JSON."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_var.set(request_id)
    start = time.monotonic()

    extra: dict[str, Any] = {
        "event": "http_request",
        "method": request.method,
        "path": request.url.path,
    }
    if request.url.query:
        extra["query"] = str(request.url.query)
    logger.info("http_request", extra=extra)

    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info(
            "http_response",
            extra={
                "event": "http_response",
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        logger.error(
            "http_response",
            extra={
                "event": "http_response",
                "status": 500,
                "duration_ms": duration_ms,
            },
        )
        raise
    finally:
        request_id_var.reset(token)


app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Mount MCP Streamable HTTP transport at /mcp (stateless — no per-pod session state)
mcp_app = mcp.streamable_http_app()
app.mount("/mcp", mcp_app)
app.add_route("/metrics", metrics_endpoint)


# -- Dashboard Routes --


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)) -> HTMLResponse:
    """Main dashboard page."""
    tool_stats: list[Any] = []
    recent_logs: list[Any] = []
    total = 0

    try:
        tool_stats = list(
            (
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
        )

        recent_logs = list(
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
        request,
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
async def healthz() -> JSONResponse:
    """Liveness probe — returns 200 if the process is alive."""
    return JSONResponse({"status": "alive"})


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Readiness probe — returns 503 only if DB is down. Upstream proxy status is
    reported but does not gate readiness, so core API (tickets, reviews, REST)
    stays reachable even when upstream MCP servers are temporarily disconnected."""
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.warning("Health check DB probe failed: %s", e)
        db_ok = False

    tool_names = get_tool_names()
    connected = 0
    total = 0

    if proxy_manager:
        ps = proxy_manager.get_status()
        connected = ps["connected"]
        total = ps["total_servers"]

    proxy_healthy = connected >= total / 2 if total > 0 else True

    result: dict[str, Any] = {
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
async def list_tools() -> dict[str, Any]:
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
async def proxy_status_endpoint() -> dict[str, Any]:
    """Get proxy manager status — all upstream connections."""
    if not proxy_manager:
        return {"enabled": False, "message": "Proxy is disabled"}
    return proxy_manager.get_status()


@app.post("/api/proxy/reconnect/{server_name}")
async def proxy_reconnect(server_name: str) -> dict[str, Any]:
    """Reconnect to a specific upstream MCP server."""
    if not proxy_manager:
        return {"error": "Proxy is disabled"}
    success = await proxy_manager.reconnect(server_name)
    return {"server": server_name, "reconnected": success}


@app.get("/api/proxy/tools")
async def proxy_tool_map() -> dict[str, Any]:
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
) -> dict[str, Any]:
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


@app.post("/api/tickets", response_model=None)
async def api_create_ticket(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Create a new ticket. Used by automated scripts (e.g. canary runner) and the dispatcher."""
    from mcp_hub.models.ticket import VALID_PRIORITIES

    body = await request.json()
    required = ["title", "description", "from_role", "to_role"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    priority = body.get("priority", "medium")
    if priority not in VALID_PRIORITIES:
        return JSONResponse(
            {"error": f"Invalid priority '{priority}'. Valid: {sorted(VALID_PRIORITIES)}"},
            status_code=400,
        )

    ticket = Ticket(
        title=body["title"],
        description=body["description"],
        from_role=body["from_role"],
        to_role=body["to_role"],
        priority=priority,
        status="queued",
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    logger.info("Ticket #%d created via REST: %s", ticket.id, ticket.title)
    return {"id": ticket.id, "title": ticket.title, "status": ticket.status}


@app.get("/api/tickets/{ticket_id}", response_model=None)
async def api_get_ticket(
    ticket_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
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


@app.patch("/api/tickets/{ticket_id}", response_model=None)
async def api_update_ticket(
    ticket_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Update ticket fields. Used by the dispatcher for triage and status updates."""
    ticket = await session.get(Ticket, ticket_id)
    if not ticket:
        return JSONResponse({"error": f"Ticket #{ticket_id} not found"}, status_code=404)

    body = await request.json()
    updates = []

    old_status: str | None = None
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
        old_status = ticket.status
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
        if old_status is not None:
            await write_audit_entry(
                session, "ticket", ticket_id, old_status, ticket.status, changed_by="api"
            )
        await session.commit()

    return {"id": ticket_id, "updated": updates}


# -- Improvement REST endpoints --


@app.get("/api/improvements", response_model=None)
async def api_list_improvements(
    status: str = "",
    category: str = "",
    severity: str = "",
    agent_role: str = "",
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """List improvements with optional filters."""
    from mcp_hub.models.improvement import (
        VALID_CATEGORIES,
        VALID_IMPROVEMENT_STATUSES,
        VALID_SEVERITIES,
        Improvement,
    )

    query = select(Improvement).order_by(Improvement.created_at.desc())
    if status:
        if status not in VALID_IMPROVEMENT_STATUSES:
            return JSONResponse({"error": f"Invalid status '{status}'"}, status_code=400)
        query = query.where(Improvement.status == status)
    if category:
        if category not in VALID_CATEGORIES:
            return JSONResponse({"error": f"Invalid category '{category}'"}, status_code=400)
        query = query.where(Improvement.category == category)
    if severity:
        if severity not in VALID_SEVERITIES:
            return JSONResponse({"error": f"Invalid severity '{severity}'"}, status_code=400)
        query = query.where(Improvement.severity == severity)
    if agent_role:
        query = query.where(Improvement.agent_role == agent_role)
    query = query.limit(min(limit, 100))

    improvements = (await session.execute(query)).scalars().all()
    return {
        "improvements": [
            {
                "id": i.id,
                "agent_role": i.agent_role,
                "category": i.category,
                "severity": i.severity,
                "status": i.status,
                "title": i.title,
                "description": i.description,
                "related_ticket_id": i.related_ticket_id,
                "comments_count": i.comments_count,
                "created_at": i.created_at.isoformat(),
                "updated_at": i.updated_at.isoformat(),
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
            }
            for i in improvements
        ],
        "total": len(improvements),
    }


@app.get("/api/improvements/{improvement_id}", response_model=None)
async def api_get_improvement(
    improvement_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Get a single improvement by ID with comments."""
    from sqlalchemy.orm import selectinload as si

    from mcp_hub.models.improvement import Improvement  # noqa: F401

    result = await session.execute(
        select(Improvement)
        .where(Improvement.id == improvement_id)
        .options(si(Improvement.comments))
    )
    improvement = result.scalar_one_or_none()
    if not improvement:
        return JSONResponse({"error": f"Improvement #{improvement_id} not found"}, status_code=404)
    return {
        "id": improvement.id,
        "agent_role": improvement.agent_role,
        "category": improvement.category,
        "severity": improvement.severity,
        "status": improvement.status,
        "title": improvement.title,
        "description": improvement.description,
        "related_ticket_id": improvement.related_ticket_id,
        "comments_count": improvement.comments_count,
        "created_at": improvement.created_at.isoformat(),
        "updated_at": improvement.updated_at.isoformat(),
        "resolved_at": improvement.resolved_at.isoformat() if improvement.resolved_at else None,
        "comments": [
            {
                "id": c.id,
                "role": c.role,
                "content": c.content,
                "created_at": c.created_at.isoformat(),
            }
            for c in improvement.comments
        ],
    }


@app.post("/api/improvements", response_model=None)
async def api_create_improvement(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Create an improvement record (admin/internal use)."""
    from mcp_hub.models.improvement import VALID_CATEGORIES, VALID_SEVERITIES, Improvement
    from mcp_hub.models.ticket import VALID_ROLES

    body = await request.json()
    required = ["agent_role", "category", "severity", "title", "description"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    if body["agent_role"] not in VALID_ROLES:
        return JSONResponse(
            {"error": f"Invalid agent_role '{body['agent_role']}'"}, status_code=400
        )
    if body["category"] not in VALID_CATEGORIES:
        return JSONResponse({"error": f"Invalid category '{body['category']}'"}, status_code=400)
    if body["severity"] not in VALID_SEVERITIES:
        return JSONResponse({"error": f"Invalid severity '{body['severity']}'"}, status_code=400)

    improvement = Improvement(
        agent_role=body["agent_role"],
        category=body["category"],
        severity=body["severity"],
        title=body["title"][:255],
        description=body["description"][:8192],
        related_ticket_id=body.get("related_ticket_id"),
    )
    session.add(improvement)
    await session.commit()
    await session.refresh(improvement)
    return {"id": improvement.id, "title": improvement.title, "status": improvement.status}


@app.patch("/api/improvements/{improvement_id}", response_model=None)
async def api_update_improvement(
    improvement_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Update improvement status or severity."""
    from datetime import UTC, datetime

    from mcp_hub.models.improvement import (
        VALID_IMPROVEMENT_STATUSES,
        VALID_IMPROVEMENT_TRANSITIONS,
        VALID_SEVERITIES,
        Improvement,
    )

    result = await session.execute(select(Improvement).where(Improvement.id == improvement_id))
    improvement = result.scalar_one_or_none()
    if not improvement:
        return JSONResponse({"error": f"Improvement #{improvement_id} not found"}, status_code=404)

    body = await request.json()
    updates = []

    if "status" in body:
        new_status = body["status"]
        if new_status not in VALID_IMPROVEMENT_STATUSES:
            return JSONResponse({"error": f"Invalid status '{new_status}'"}, status_code=400)
        allowed = VALID_IMPROVEMENT_TRANSITIONS.get(improvement.status, set())
        if new_status not in allowed:
            return JSONResponse(
                {"error": f"Cannot transition from '{improvement.status}' to '{new_status}'"},
                status_code=400,
            )
        improvement.status = new_status
        if new_status == "resolved":
            improvement.resolved_at = datetime.now(UTC)
        updates.append(f"status={new_status}")

    if "severity" in body:
        new_severity = body["severity"]
        if new_severity not in VALID_SEVERITIES:
            return JSONResponse({"error": f"Invalid severity '{new_severity}'"}, status_code=400)
        improvement.severity = new_severity
        updates.append(f"severity={new_severity}")

    if not updates:
        return JSONResponse({"error": "No fields to update"}, status_code=400)

    await session.commit()
    return {"id": improvement.id, "updates": updates}


@app.post("/api/improvements/{improvement_id}/comments", response_model=None)
async def api_add_improvement_comment(
    improvement_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Add a comment to an improvement."""
    from mcp_hub.models.improvement import Improvement, ImprovementComment
    from mcp_hub.models.ticket import VALID_ROLES

    result = await session.execute(select(Improvement).where(Improvement.id == improvement_id))
    improvement = result.scalar_one_or_none()
    if not improvement:
        return JSONResponse({"error": f"Improvement #{improvement_id} not found"}, status_code=404)

    body = await request.json()
    if "role" not in body or "content" not in body:
        return JSONResponse({"error": "Missing required fields: role, content"}, status_code=400)
    if body["role"] not in VALID_ROLES:
        return JSONResponse({"error": f"Invalid role '{body['role']}'"}, status_code=400)
    if not body["content"].strip():
        return JSONResponse({"error": "Content cannot be empty"}, status_code=400)

    comment = ImprovementComment(
        improvement_id=improvement_id,
        role=body["role"],
        content=body["content"].strip(),
    )
    session.add(comment)
    improvement.comments_count += 1
    await session.commit()
    await session.refresh(comment)
    return {"id": comment.id, "improvement_id": improvement_id}


# -- MR Review API (for dispatcher) --


@app.get("/api/reviews")
async def api_list_reviews(
    project_id: int = 0,
    verdict: str = "",
    author_role: str = "",
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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
                "rebase_ticket_id": r.rebase_ticket_id,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
                "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                "merged_at": r.merged_at.isoformat() if r.merged_at else None,
            }
            for r in reviews
        ],
        "total": len(reviews),
    }


@app.get("/api/reviews/{review_id}", response_model=None)
async def api_get_review(
    review_id: int, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
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
        "rebase_ticket_id": review.rebase_ticket_id,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "merged_at": review.merged_at.isoformat() if review.merged_at else None,
    }


@app.post("/api/reviews", response_model=None)
async def api_create_review(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Create or update an MR review record. Used by the dispatcher when it finds a new MR."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    body = await request.json()
    required = ["project_id", "mr_iid", "title", "source_branch"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    # Snapshot old state for audit logging before the atomic upsert
    old_row = (
        await session.execute(
            select(MrReview.id, MrReview.verdict, MrReview.commit_sha).where(
                MrReview.project_id == body["project_id"],
                MrReview.mr_iid == body["mr_iid"],
            )
        )
    ).one_or_none()

    raw_mr_url = body.get("mr_url")
    clean_mr_url = raw_mr_url.replace(":31356", "") if raw_mr_url else raw_mr_url

    insert_values = {
        "project_id": body["project_id"],
        "mr_iid": body["mr_iid"],
        "title": body["title"],
        "source_branch": body["source_branch"],
        "author_role": body.get("author_role"),
        "pipeline_status": body.get("pipeline_status"),
        "verdict": "pending",
        "lines_changed": body.get("lines_changed"),
        "commit_sha": body.get("commit_sha"),
        "mr_url": clean_mr_url,
    }

    update_on_conflict = {
        "title": body["title"],
        "source_branch": body["source_branch"],
        "verdict": "pending",
        "reason": None,
        "details": None,
        "reviewed_at": None,
    }
    for field in ("author_role", "pipeline_status", "lines_changed", "commit_sha"):
        if field in body:
            update_on_conflict[field] = body[field]
    if "mr_url" in body:
        update_on_conflict["mr_url"] = clean_mr_url

    stmt = (
        pg_insert(MrReview)
        .values(**insert_values)
        .on_conflict_do_update(constraint="uq_review_project_mr", set_=update_on_conflict)
        .returning(MrReview.id, MrReview.verdict)
    )
    result = (await session.execute(stmt)).one()
    was_update = old_row is not None

    if old_row is not None and old_row.verdict not in ("pending", None):
        old_commit = old_row.commit_sha
        new_commit = body.get("commit_sha", "unknown")
        session.add(
            ReviewResetLog(
                review_id=result.id,
                old_verdict=old_row.verdict,
                old_commit_sha=old_commit,
                new_commit_sha=body.get("commit_sha"),
                reason="push-reset: new commit triggered re-review",
            )
        )
        await write_audit_entry(
            session,
            "mr_review",
            result.id,
            old_row.verdict,
            "pending",
            changed_by="api",
            reason=f"new-commit-{old_commit or 'unknown'}→{new_commit}",
        )

    await session.commit()
    return {"id": result.id, "verdict": result.verdict, "updated": was_update}


@app.patch("/api/reviews/{review_id}", response_model=None)
async def api_update_review(
    review_id: int, request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Update MR review fields. Used by the dispatcher after sonnet review."""
    review = await session.get(MrReview, review_id)
    if not review:
        return JSONResponse({"error": f"Review #{review_id} not found"}, status_code=404)

    body = await request.json()
    updates = []
    audit_transition: tuple[str, str] | None = None

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
        audit_transition = (old_verdict, new_verdict)

        # Auto-set reviewed_at when transitioning from pending to a decided verdict
        if old_verdict == "pending" and new_verdict != "pending" and "reviewed_at" not in body:
            review.reviewed_at = dt.now(UTC)
            updates.append("reviewed_at auto-set")

        # Auto-set merged_at when transitioning to merged
        if new_verdict == "merged" and "merged_at" not in body:
            review.merged_at = dt.now(UTC)
            updates.append("merged_at auto-set")

    for field in [
        "reason",
        "details",
        "reviewer_model",
        "pipeline_status",
        "commit_sha",
        "lines_changed",
        "rebase_ticket_id",
    ]:
        if field in body:
            setattr(review, field, body[field])
            updates.append(f"{field} updated")

    if "reviewed_at" in body:
        review.reviewed_at = dt.fromisoformat(body["reviewed_at"])
        updates.append("reviewed_at set")
    if "merged_at" in body:
        review.merged_at = dt.fromisoformat(body["merged_at"])
        updates.append("merged_at set")

    if updates:
        if audit_transition is not None:
            await write_audit_entry(
                session,
                "mr_review",
                review_id,
                audit_transition[0],
                audit_transition[1],
                changed_by="api",
                reason=body.get("reason"),
            )
        await session.commit()

    return {"id": review_id, "updated": updates}


@app.post("/api/reviews/claim", response_model=None)
async def api_claim_review(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Set author_role on an existing review by (project_id, mr_iid).

    Called by agents immediately after pushing an MR so mr_review_mine() returns results.
    Returns 404 if the dispatcher hasn't created the record yet — agent should retry.
    """
    body = await request.json()
    for field in ["project_id", "mr_iid", "author_role"]:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    review = (
        await session.execute(
            select(MrReview).where(
                MrReview.project_id == body["project_id"],
                MrReview.mr_iid == body["mr_iid"],
            )
        )
    ).scalar_one_or_none()

    if not review:
        return JSONResponse(
            {
                "error": (
                    f"No review found for PID={body['project_id']} !{body['mr_iid']}. "
                    "Dispatcher may not have created it yet — retry in ~1 minute."
                )
            },
            status_code=404,
        )

    review.author_role = body["author_role"]
    await session.commit()
    return {
        "id": review.id,
        "project_id": review.project_id,
        "mr_iid": review.mr_iid,
        "author_role": review.author_role,
    }


@app.get("/api/canary-runs")
async def api_list_canary_runs(
    limit: int = 20,
    outcome: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List recent MR canary run results. Used by dashboards and monitoring."""
    query = select(MrCanaryRun).order_by(MrCanaryRun.created_at.desc()).limit(min(limit, 100))
    if outcome:
        query = query.where(MrCanaryRun.outcome == outcome)
    runs = (await session.execute(query)).scalars().all()
    return {
        "runs": [
            {
                "id": r.id,
                "project_id": r.project_id,
                "branch": r.branch,
                "mr_iid": r.mr_iid,
                "outcome": r.outcome,
                "elapsed_seconds": r.elapsed_seconds,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
            }
            for r in runs
        ],
        "total": len(runs),
    }


@app.post("/api/canary-runs", response_model=None)
async def api_record_canary_run(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Record a canary run result. Called by the canary runner script after each run."""
    from mcp_hub.models.canary import VALID_OUTCOMES

    body = await request.json()
    required = ["branch", "outcome", "elapsed_seconds"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    outcome = body["outcome"]
    if outcome not in VALID_OUTCOMES:
        return JSONResponse(
            {"error": f"Invalid outcome '{outcome}'. Valid: {sorted(VALID_OUTCOMES)}"},
            status_code=400,
        )

    run = MrCanaryRun(
        project_id=body.get("project_id", 26),
        branch=body["branch"],
        mr_iid=body.get("mr_iid") or None,
        outcome=outcome,
        elapsed_seconds=int(body["elapsed_seconds"]),
        error=body.get("error") or None,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    logger.info("Canary run #%d recorded: %s (%s)", run.id, outcome, run.branch)
    return {"id": run.id, "outcome": outcome, "branch": run.branch}


# -- Solution Patterns API --


@app.get("/api/solution-patterns/aggregate", response_model=None)
async def api_aggregate_solution_patterns(
    group_by: str = "role",
    since: str = "",
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """Aggregate solution patterns. group_by: role|model|outcome. since: ISO date."""
    from sqlalchemy import func as sqlfunc

    group_map = {
        "role": SolutionPattern.agent_role,
        "model": SolutionPattern.model_assigned,
        "outcome": SolutionPattern.outcome,
    }
    if group_by not in group_map:
        return JSONResponse(
            {"error": f"Invalid group_by: {group_by}. Valid: role, model, outcome"},
            status_code=400,
        )

    group_col = group_map[group_by]
    query = select(
        group_col.label("group_value"),
        sqlfunc.count().label("count"),
        sqlfunc.avg(SolutionPattern.duration_seconds).label("avg_duration"),
        sqlfunc.max(SolutionPattern.duration_seconds).label("max_duration"),
        sqlfunc.avg(SolutionPattern.tool_calls).label("avg_tool_calls"),
        sqlfunc.avg(SolutionPattern.errors).label("avg_errors"),
        sqlfunc.avg(SolutionPattern.mr_pipeline_runs).label("avg_pipeline_runs"),
    ).group_by(group_col)

    if since:
        try:
            since_dt = dt.fromisoformat(since)
        except ValueError:
            return JSONResponse({"error": f"Invalid since date: {since}"}, status_code=400)
        query = query.where(SolutionPattern.created_at >= since_dt)

    rows = (await session.execute(query)).all()

    def safe_rate(errors: float, tools: float) -> float:
        if not tools or tools == 0:
            return 0.0
        return round(errors / tools, 4)

    return {
        "group_by": group_by,
        "since": since,
        "aggregates": [
            {
                "group": r.group_value or "(unset)",
                "count": r.count,
                "avg_duration_seconds": round(float(r.avg_duration or 0), 1),
                "max_duration_seconds": int(r.max_duration or 0),
                "avg_tool_calls": round(float(r.avg_tool_calls or 0), 1),
                "avg_errors": round(float(r.avg_errors or 0), 2),
                "error_rate": safe_rate(float(r.avg_errors or 0), float(r.avg_tool_calls or 1)),
                "avg_pipeline_runs": round(float(r.avg_pipeline_runs or 0), 1),
            }
            for r in rows
        ],
        "total_groups": len(rows),
    }


@app.get("/api/solution-patterns", response_model=None)
async def api_list_solution_patterns(
    agent_role: str = "",
    outcome: str = "",
    since: str = "",
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any] | JSONResponse:
    """List solution pattern records with optional filters."""
    query = select(SolutionPattern).order_by(SolutionPattern.created_at.desc())
    if agent_role:
        query = query.where(SolutionPattern.agent_role == agent_role)
    if outcome:
        query = query.where(SolutionPattern.outcome == outcome)
    if since:
        try:
            since_dt = dt.fromisoformat(since)
        except ValueError:
            return JSONResponse({"error": f"Invalid since date: {since}"}, status_code=400)
        query = query.where(SolutionPattern.created_at >= since_dt)
    query = query.limit(min(limit, 100))

    rows = (await session.execute(query)).scalars().all()
    return {
        "patterns": [
            {
                "id": r.id,
                "ticket_id": r.ticket_id,
                "agent_role": r.agent_role,
                "model_assigned": r.model_assigned,
                "duration_seconds": r.duration_seconds,
                "tool_calls": r.tool_calls,
                "unique_tool_calls": r.unique_tool_calls,
                "retries": r.retries,
                "errors": r.errors,
                "mr_iid": r.mr_iid,
                "mr_pipeline_runs": r.mr_pipeline_runs,
                "freeze_gaps_count": r.freeze_gaps_count,
                "freeze_gaps_total_seconds": r.freeze_gaps_total_seconds,
                "estimated_cost_usd": (
                    float(r.estimated_cost_usd) if r.estimated_cost_usd else None
                ),
                "outcome": r.outcome,
                "notes": r.notes,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "total": len(rows),
    }


@app.post("/api/solution-patterns", response_model=None)
async def api_create_solution_pattern(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any] | JSONResponse:
    """Create a solution pattern record. Used by the dispatcher after ticket completion."""
    body = await request.json()
    required = ["ticket_id", "agent_role", "duration_seconds", "outcome"]
    for field in required:
        if field not in body:
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    if body["outcome"] not in SP_VALID_OUTCOMES:
        return JSONResponse(
            {"error": (f"Invalid outcome: {body['outcome']}. Valid: {sorted(SP_VALID_OUTCOMES)}")},
            status_code=400,
        )

    pattern = SolutionPattern(
        ticket_id=body["ticket_id"],
        agent_role=body["agent_role"],
        model_assigned=body.get("model_assigned"),
        duration_seconds=body["duration_seconds"],
        tool_calls=body.get("tool_calls", 0),
        unique_tool_calls=body.get("unique_tool_calls", 0),
        retries=body.get("retries", 0),
        errors=body.get("errors", 0),
        mr_iid=body.get("mr_iid"),
        mr_pipeline_runs=body.get("mr_pipeline_runs", 0),
        freeze_gaps_count=body.get("freeze_gaps_count", 0),
        freeze_gaps_total_seconds=body.get("freeze_gaps_total_seconds", 0),
        estimated_cost_usd=body.get("estimated_cost_usd"),
        outcome=body["outcome"],
        notes=body.get("notes"),
    )
    session.add(pattern)
    await session.commit()
    await session.refresh(pattern)
    return {
        "id": pattern.id,
        "ticket_id": pattern.ticket_id,
        "created_at": pattern.created_at.isoformat(),
    }


@app.get("/api/service-locks")
async def api_list_service_locks(
    active_only: bool = True,
    service: str = "",
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """List service locks. Read-only endpoint for dashboards.

    active_only=true (default): only locks with released_at IS NULL
    service: filter by service name
    """
    from mcp_hub.models.service_lock import ServiceLock

    query = select(ServiceLock).order_by(ServiceLock.acquired_at.desc()).limit(min(limit, 200))
    if active_only:
        query = query.where(ServiceLock.released_at.is_(None))
    if service:
        query = query.where(ServiceLock.service == service.strip().lower())

    locks = (await session.execute(query)).scalars().all()
    return {
        "locks": [
            {
                "id": lock.id,
                "service": lock.service,
                "holder_role": lock.holder_role,
                "holder_session_id": lock.holder_session_id,
                "reason": lock.reason,
                "acquired_at": lock.acquired_at.isoformat(),
                "released_at": lock.released_at.isoformat() if lock.released_at else None,
                "expected_back_at": (
                    lock.expected_back_at.isoformat() if lock.expected_back_at else None
                ),
            }
            for lock in locks
        ],
        "total": len(locks),
    }


@app.get("/api/logs")
async def get_logs(
    limit: int = 50, tool_name: str = "", session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
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
