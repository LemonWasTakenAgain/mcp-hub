"""MCP Server - registers all tools and serves them over SSE transport."""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.sse import TransportSecuritySettings

from mcp_hub.tools import (
    db_audit_tools,
    email_tools,
    gitlab_tools,
    homelab_tools,
    k8s_tools,
    marketing_tools,
    mr_review_tools,
    ticket_tools,
)

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


# -- MR Review Tools --


@mcp.tool()
async def mr_review_list(
    project_id: int = 0, author_role: str = "", verdict: str = "", limit: int = 20
) -> str:
    """List MR reviews. Filter by project_id, author_role, or verdict."""
    return await mr_review_tools.list_reviews(project_id, author_role, verdict, limit)


@mcp.tool()
async def mr_review_get(project_id: int, mr_iid: int) -> str:
    """Get full review details for a specific merge request."""
    return await mr_review_tools.get_review(project_id, mr_iid)


@mcp.tool()
async def mr_review_mine(author_role: str) -> str:
    """List your open (non-merged) MRs with verdict and pipeline status."""
    return await mr_review_tools.my_mrs(author_role)


@mcp.tool()
async def mr_review_claim(project_id: int, mr_iid: int, author_role: str) -> str:
    """Claim an MR review by setting your author_role so mr_review_mine() returns it.

    Call this immediately after pushing an MR. The dispatcher creates the review record
    within ~1 minute; if you get a 'not found' response, retry after a minute.
    """
    return await mr_review_tools.claim_mr(project_id, mr_iid, author_role)


@mcp.tool()
async def mr_review_retry(project_id: int, mr_iid: int) -> str:
    """Reset a rejected or needs_human MR review to pending for re-review.

    Use when an MR was rejected for a transient reason (e.g. CI was flaky but is now
    green) or after the author has pushed fixes. The automated dispatcher will pick up
    the pending review and re-run within ~1 minute.
    """
    return await mr_review_tools.retry_review(project_id, mr_iid)


# -- Marketing Tools --


@mcp.tool()
async def marketing_project_create(
    name: str,
    description: str = "",
    target_audience: str = "",
    value_prop: str = "",
    status: str = "idea",
    website_url: str = "",
    repo_url: str = "",
    gitlab_project_id: int = 0,
) -> str:
    """Create a new marketing project to track a product or initiative."""
    return await marketing_tools.create_project(
        name,
        description,
        target_audience,
        value_prop,
        status,
        website_url,
        repo_url,
        gitlab_project_id,
    )


@mcp.tool()
async def marketing_project_update(
    project_id: int,
    name: str = "",
    description: str = "",
    target_audience: str = "",
    value_prop: str = "",
    status: str = "",
    website_url: str = "",
    repo_url: str = "",
    gitlab_project_id: int = 0,
) -> str:
    """Update a marketing project's fields."""
    return await marketing_tools.update_project(
        project_id,
        name,
        description,
        target_audience,
        value_prop,
        status,
        website_url,
        repo_url,
        gitlab_project_id,
    )


@mcp.tool()
async def marketing_project_get(project_id: int) -> str:
    """Get full details of a marketing project including all campaigns."""
    return await marketing_tools.get_project(project_id)


@mcp.tool()
async def marketing_project_list(status: str = "") -> str:
    """List marketing projects, filtered by status (idea/building/launched/growing/sunset)."""
    return await marketing_tools.list_projects(status)


@mcp.tool()
async def marketing_campaign_create(
    project_id: int,
    name: str,
    channel: str,
    platform: str = "",
    status: str = "planned",
    budget_cents: int = 0,
    goal: str = "",
    source: str = "",
) -> str:
    """Create a campaign under a marketing project."""
    return await marketing_tools.create_campaign(
        project_id, name, channel, platform, status, budget_cents, goal, source
    )


@mcp.tool()
async def marketing_campaign_update(
    campaign_id: int,
    name: str = "",
    description: str = "",
    channel: str = "",
    platform: str = "",
    status: str = "",
    budget_cents: int = -1,
    spend_cents: int = -1,
    revenue_cents: int = -1,
    goal: str = "",
    outcome: str = "",
    lessons_learned: str = "",
) -> str:
    """Update a campaign's fields. Pass -1 for budget/spend/revenue to leave unchanged."""
    return await marketing_tools.update_campaign(
        campaign_id,
        name,
        description,
        channel,
        platform,
        status,
        budget_cents,
        spend_cents,
        revenue_cents,
        goal,
        outcome,
        lessons_learned,
    )


@mcp.tool()
async def marketing_campaign_get(campaign_id: int) -> str:
    """Get full details of a campaign including aggregated metrics."""
    return await marketing_tools.get_campaign(campaign_id)


@mcp.tool()
async def marketing_campaign_list(project_id: int = 0, status: str = "", channel: str = "") -> str:
    """List campaigns with optional filters by project, status, or channel."""
    return await marketing_tools.list_campaigns(project_id, status, channel)


@mcp.tool()
async def marketing_metric_add(
    campaign_id: int,
    metric_date: str,
    impressions: int = 0,
    clicks: int = 0,
    conversions: int = 0,
    spend_cents: int = 0,
    revenue_cents: int = 0,
    source: str = "",
    notes: str = "",
) -> str:
    """Add or update a daily metric entry for a campaign (upserts on campaign+date+source)."""
    return await marketing_tools.add_metric(
        campaign_id,
        metric_date,
        impressions,
        clicks,
        conversions,
        spend_cents,
        revenue_cents,
        source,
        notes,
    )


@mcp.tool()
async def marketing_metric_query(
    campaign_id: int = 0, start_date: str = "", end_date: str = ""
) -> str:
    """Query metrics with optional filters by campaign and date range (YYYY-MM-DD)."""
    return await marketing_tools.query_metrics(campaign_id, start_date, end_date)


@mcp.tool()
async def marketing_dashboard() -> str:
    """Show marketing dashboard with all projects and health scores (green/yellow/red)."""
    return await marketing_tools.dashboard()


# -- Email Tools --


@mcp.tool()
async def email_sync(limit: int = 200) -> str:
    """Sync recent emails from Stalwart JMAP into the local database for querying."""
    return await email_tools.sync_emails(limit)


@mcp.tool()
async def email_search(
    query: str = "",
    from_addr: str = "",
    to_addr: str = "",
    days: int = 30,
    unread_only: bool = False,
    flagged_only: bool = False,
    limit: int = 25,
) -> str:
    """Search cached emails by subject, sender, recipient, or date range."""
    return await email_tools.search_emails(
        query,
        from_addr,
        to_addr,
        days,
        unread_only,
        flagged_only,
        limit,
    )


@mcp.tool()
async def email_stats(days: int = 30) -> str:
    """Get email statistics: volume, unread count, top senders, storage usage."""
    return await email_tools.email_stats(days)


@mcp.tool()
async def email_get(jmap_id: str) -> str:
    """Fetch full email body from Stalwart by JMAP message ID (from search results)."""
    return await email_tools.email_get(jmap_id)


# -- Database Audit Tools --


@mcp.tool()
async def db_stats() -> str:
    """Show row counts and disk usage for all MCP Hub database tables."""
    return await db_audit_tools.db_stats()


@mcp.tool()
async def db_recent_activity(hours: int = 24) -> str:
    """Show recent activity across tickets, MR reviews, emails, and tool logs."""
    return await db_audit_tools.db_recent_activity(hours)


@mcp.tool()
async def db_search(query: str, table: str = "", limit: int = 20) -> str:
    """Full-text search across all database tables (tickets, reviews, emails, marketing, logs)."""
    return await db_audit_tools.db_search(query, table, limit)


@mcp.tool()
async def db_table_detail(table: str, limit: int = 20, offset: int = 0) -> str:
    """Browse rows in a specific database table with pagination."""
    return await db_audit_tools.db_table_detail(table, limit, offset)
