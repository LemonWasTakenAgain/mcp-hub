"""MCP Server - registers all tools and serves them over SSE transport."""

from mcp.server.fastmcp import FastMCP

from mcp_hub.tools import gitlab_tools, homelab_tools, k8s_tools

mcp = FastMCP(
    "MCP Hub",
    instructions=(
        "Internal homelab MCP server providing GitLab, Kubernetes, "
        "and system administration tools."
    ),
)

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
