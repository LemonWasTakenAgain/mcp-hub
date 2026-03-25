"""FastAPI application - web dashboard + MCP SSE endpoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mcp_hub.config import settings
from mcp_hub.database import engine, get_session
from mcp_hub.mcp_server import mcp
from mcp_hub.models import Base, ToolLog

logger = logging.getLogger("mcp_hub")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logger.info("MCP Hub starting up")

    # Auto-create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")

    yield

    await engine.dispose()
    logger.info("MCP Hub shut down")


app = FastAPI(
    title="MCP Hub",
    description="Internal MCP server and AI tools platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Mount MCP SSE transport at /mcp
mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)


# -- Dashboard Routes --

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    """Main dashboard page."""
    # Get tool usage stats
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

    # Get recent invocations
    recent_logs = (
        await session.execute(
            select(ToolLog).order_by(ToolLog.created_at.desc()).limit(20)
        )
    ).scalars().all()

    # Total invocations
    total = (await session.execute(select(func.count(ToolLog.id)))).scalar() or 0

    # List registered tools from the MCP server
    registered_tools = sorted(mcp._tool_manager._tools.keys())

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "tool_stats": tool_stats,
            "recent_logs": recent_logs,
            "total_invocations": total,
            "registered_tools": registered_tools,
            "tool_count": len(registered_tools),
        },
    )


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    """Health check endpoint."""
    try:
        await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    registered_tools = list(mcp._tool_manager._tools.keys())
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "mcp_tools": len(registered_tools),
        "version": "0.1.0",
    }


@app.get("/api/tools")
async def list_tools():
    """List all registered MCP tools."""
    tools = []
    for name, tool in mcp._tool_manager._tools.items():
        tools.append({
            "name": name,
            "description": tool.description,
        })
    return {"tools": tools}


@app.get("/api/logs")
async def get_logs(
    limit: int = 50, tool_name: str = "", session: AsyncSession = Depends(get_session)
):
    """Get tool invocation logs."""
    query = select(ToolLog).order_by(ToolLog.created_at.desc()).limit(min(limit, 200))
    if tool_name:
        query = query.where(ToolLog.tool_name == tool_name)
    logs = (await session.execute(query)).scalars().all()
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
