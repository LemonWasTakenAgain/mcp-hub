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
from mcp_hub.models import Base, ToolLog
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
    """Readiness probe — returns 503 if DB is down or majority of upstreams disconnected."""
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

    healthy = db_ok and (connected >= total / 2 if total > 0 else True)

    result = {
        "status": "healthy" if healthy else "degraded",
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
        }

    return JSONResponse(content=result, status_code=200 if healthy else 503)


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
