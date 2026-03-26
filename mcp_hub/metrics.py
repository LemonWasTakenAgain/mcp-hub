"""Prometheus metrics for MCP Hub."""

from prometheus_client import Counter, Gauge, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

# Tool invocation metrics
TOOL_CALLS = Counter(
    "mcp_hub_tool_calls_total",
    "Total MCP tool invocations",
    ["tool_name", "status"],
)

TOOL_DURATION = Histogram(
    "mcp_hub_tool_duration_seconds",
    "Tool call duration in seconds",
    ["tool_name"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

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
