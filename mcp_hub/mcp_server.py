"""MCP Server - registers all tools and serves them over SSE transport."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.sse import TransportSecuritySettings

from mcp_hub.tools import gitlab_tools, homelab_tools, k8s_tools, ticket_tools

# Allow the MCP Hub hostname for DNS rebinding protection
_allowed_hosts = ["localhost", "localhost:8500", "127.0.0.1:8500", "192.168.1.40:8500"]
_default_hosts = "mcp-hub.steelcanvas.studio,mcp.steelcanvas.studio"
for _host in os.environ.get("MH_ALLOWED_HOSTS", _default_hosts).split(","):
    _host = _host.strip()
    if _host:
        _allowed_hosts.append(_host)

mcp = FastMCP(
    "MCP Hub",
    instructions=(
        "Internal homelab MCP server providing GitLab, Kubernetes, and system administration tools."
    ),
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    ),
)


# -- Public API wrappers for tool manager access --
# Avoids direct access to mcp._tool_manager._tools throughout the codebase.


def get_registered_tools() -> dict:
    """Get all registered tools from the MCP server."""
    return dict(mcp._tool_manager._tools)


def get_tool_names() -> list[str]:
    """Get sorted list of registered tool names."""
    return sorted(mcp._tool_manager._tools.keys())


def register_tool(name: str, tool) -> None:
    """Register a tool on the MCP server by name."""
    mcp._tool_manager._tools[name] = tool


def unregister_tool(name: str) -> None:
    """Remove a tool from the MCP server."""
    mcp._tool_manager._tools.pop(name, None)


# -- GitLab Tools --


@mcp.tool()
async def gitlab_list_projects(search: str = "", per_page: int = 20) -> str:
    """List GitLab projects, optionally filtered by search term."""
    return await gitlab_tools.list_projects(search, per_page)


@mcp.tool()
async def gitlab_get_pipelines(project_id: int, per_page: int = 10) -> str:
    """Get recent CI/CD pipelines for a GitLab project."""
    return await gitlab_tools.get_project_pipelines(project_id, per_page)


@mcp.tool()
async def gitlab_get_pipeline_jobs(project_id: int, pipeline_id: int) -> str:
    """Get jobs for a specific GitLab CI pipeline."""
    return await gitlab_tools.get_pipeline_jobs(project_id, pipeline_id)


@mcp.tool()
async def gitlab_list_merge_requests(
    project_id: int, state: str = "opened", per_page: int = 10
) -> str:
    """List merge requests for a GitLab project."""
    return await gitlab_tools.list_merge_requests(project_id, state, per_page)


@mcp.tool()
async def gitlab_create_project(name: str, namespace_id: int | None = None) -> str:
    """Create a new GitLab project."""
    return await gitlab_tools.create_project(name, namespace_id)


# -- Kubernetes Tools --


@mcp.tool()
async def k8s_cluster_status() -> str:
    """Get Kubernetes cluster node status and resources."""
    return await k8s_tools.get_cluster_status()


@mcp.tool()
async def k8s_list_namespaces() -> str:
    """List all Kubernetes namespaces."""
    return await k8s_tools.list_namespaces()


@mcp.tool()
async def k8s_get_pods(namespace: str = "default") -> str:
    """List pods in a Kubernetes namespace."""
    return await k8s_tools.get_namespace_pods(namespace)


@mcp.tool()
async def k8s_get_services(namespace: str = "") -> str:
    """List Kubernetes services. Leave namespace empty for all."""
    return await k8s_tools.get_services(namespace)


@mcp.tool()
async def k8s_get_deployments(namespace: str = "") -> str:
    """List Kubernetes deployments with replica status."""
    return await k8s_tools.get_deployments(namespace)


# -- Homelab Tools --


@mcp.tool()
async def homelab_system_info() -> str:
    """Get system information for the MCP Hub host."""
    return await homelab_tools.system_info()


@mcp.tool()
async def homelab_ping(host: str) -> str:
    """Ping a host on the network."""
    return await homelab_tools.ping_host(host)


@mcp.tool()
async def homelab_check_service(host: str, port: int) -> str:
    """Check if a TCP service is reachable."""
    return await homelab_tools.check_service(host, port)


@mcp.tool()
async def homelab_dns_lookup(hostname: str) -> str:
    """Perform a DNS lookup."""
    return await homelab_tools.dns_lookup(hostname)


@mcp.tool()
async def homelab_http_check(url: str) -> str:
    """Check an HTTP endpoint's status and response time."""
    return await homelab_tools.http_check(url)


# -- Ticket Queue Tools --


@mcp.tool()
async def ticket_create(
    title: str, description: str, from_role: str, to_role: str, priority: str = "medium"
) -> str:
    """Create a cross-agent ticket. Use when you need work done outside your scope."""
    return await ticket_tools.create_ticket(title, description, from_role, to_role, priority)


@mcp.tool()
async def ticket_list(
    status: str = "", from_role: str = "", to_role: str = "", limit: int = 20
) -> str:
    """List tickets with optional filters by status, sender role, or target role."""
    return await ticket_tools.list_tickets(status, from_role, to_role, limit)


@mcp.tool()
async def ticket_get(ticket_id: int) -> str:
    """Get full ticket details including comments, triage info, and result."""
    return await ticket_tools.get_ticket(ticket_id)


@mcp.tool()
async def ticket_update(
    ticket_id: int, status: str = "", result: str = "", denial_reason: str = ""
) -> str:
    """Update a ticket's status, result, or denial reason."""
    return await ticket_tools.update_ticket(ticket_id, status, result, denial_reason)


@mcp.tool()
async def ticket_comment(ticket_id: int, role: str, content: str) -> str:
    """Add a comment to a ticket for progress notes or questions."""
    return await ticket_tools.add_comment(ticket_id, role, content)


@mcp.tool()
async def ticket_denied(from_role: str = "", limit: int = 10) -> str:
    """List denied tickets with reasons, optionally filtered by creator role."""
    return await ticket_tools.list_denied(from_role, limit)
