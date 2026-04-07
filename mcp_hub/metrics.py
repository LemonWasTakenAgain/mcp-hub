"""Prometheus metrics for MCP Hub."""

from prometheus_client import Counter, Gauge, Histogram, generate_latest
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

# Request metrics
REQUEST_LATENCY = Histogram(
    "mcp_hub_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "status"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

REQUEST_ERRORS = Counter(
    "mcp_hub_request_errors_total",
    "Total number of HTTP request errors (4xx/5xx)",
    ["method", "endpoint", "status"],
)

# Tool call metrics
TOOL_CALLS = Counter(
    "mcp_hub_tool_calls_total",
    "Total tool invocations",
    ["tool_name", "status"],
)

TOOL_LATENCY = Histogram(
    "mcp_hub_tool_duration_seconds",
    "Tool call latency in seconds",
    ["tool_name"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# Database metrics
DB_QUERY_LATENCY = Histogram(
    "mcp_hub_db_query_duration_seconds",
    "Database query latency in seconds",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
