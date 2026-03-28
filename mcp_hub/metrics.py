"""Prometheus metrics for MCP Hub."""

from prometheus_client import Gauge, generate_latest
from starlette.requests import Request
from starlette.responses import Response

# Upstream connection metrics
UPSTREAM_CONNECTED = Gauge(
    "mcp_hub_upstream_connected",
    "Whether upstream server is connected (1=yes, 0=no)",
    ["server_name"],
)

UPSTREAM_TOOLS = Gauge(
    "mcp_hub_upstream_tools_total",
    "Number of tools exposed by upstream server",
    ["server_name"],
)

# Overall gauges
TOTAL_TOOLS = Gauge(
    "mcp_hub_tools_registered_total",
    "Total number of registered MCP tools",
)


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
