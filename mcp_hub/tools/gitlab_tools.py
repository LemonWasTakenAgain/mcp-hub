"""GitLab integration tools for MCP."""

import httpx

from mcp_hub.config import settings


async def _gitlab_get(path: str) -> dict | list:
    """Make an authenticated GET request to the GitLab API."""
    async with httpx.AsyncClient(
        base_url=settings.gitlab_url,
        headers={"PRIVATE-TOKEN": settings.gitlab_token},
        timeout=30.0,
    ) as client:
        resp = await client.get(f"/api/v4{path}")
        resp.raise_for_status()
        return resp.json()


async def _gitlab_post(path: str, json: dict | None = None) -> dict:
    """Make an authenticated POST request to the GitLab API."""
    async with httpx.AsyncClient(
        base_url=settings.gitlab_url,
        headers={"PRIVATE-TOKEN": settings.gitlab_token},
        timeout=30.0,
    ) as client:
        resp = await client.post(f"/api/v4{path}", json=json)
        resp.raise_for_status()
        return resp.json()


async def list_projects(search: str = "", per_page: int = 20) -> str:
    """List GitLab projects, optionally filtered by search term.

    Args:
        search: Optional search query to filter projects
        per_page: Number of results to return (default 20, max 100)
    """
    params = f"?per_page={min(per_page, 100)}&order_by=updated_at"
    if search:
        params += f"&search={search}"
    projects = await _gitlab_get(f"/projects{params}")
    lines = []
    for p in projects:
        lines.append(
            f"- [{p['path_with_namespace']}]({p['web_url']}) "
            f"| updated: {p['last_activity_at'][:10]} "
            f"| stars: {p.get('star_count', 0)}"
        )
    return "\n".join(lines) if lines else "No projects found."


async def get_project_pipelines(project_id: int, per_page: int = 10) -> str:
    """Get recent CI/CD pipelines for a GitLab project.

    Args:
        project_id: The GitLab project ID
        per_page: Number of pipelines to return (default 10)
    """
    pipelines = await _gitlab_get(
        f"/projects/{project_id}/pipelines?per_page={min(per_page, 50)}"
    )
    lines = []
    for p in pipelines:
        lines.append(
            f"- Pipeline #{p['id']} | {p['status']} | ref: {p['ref']} "
            f"| {p['created_at'][:19]}"
        )
    return "\n".join(lines) if lines else "No pipelines found."


async def get_pipeline_jobs(project_id: int, pipeline_id: int) -> str:
    """Get jobs for a specific pipeline.

    Args:
        project_id: The GitLab project ID
        pipeline_id: The pipeline ID
    """
    jobs = await _gitlab_get(
        f"/projects/{project_id}/pipelines/{pipeline_id}/jobs"
    )
    lines = []
    for j in jobs:
        duration = f"{j.get('duration', 0):.1f}s" if j.get("duration") else "n/a"
        lines.append(
            f"- {j['name']} | {j['status']} | stage: {j['stage']} | duration: {duration}"
        )
    return "\n".join(lines) if lines else "No jobs found."


async def list_merge_requests(
    project_id: int, state: str = "opened", per_page: int = 10
) -> str:
    """List merge requests for a GitLab project.

    Args:
        project_id: The GitLab project ID
        state: MR state filter (opened, closed, merged, all)
        per_page: Number of results (default 10)
    """
    mrs = await _gitlab_get(
        f"/projects/{project_id}/merge_requests?state={state}&per_page={min(per_page, 50)}"
    )
    lines = []
    for mr in mrs:
        lines.append(
            f"- MR !{mr['iid']}: {mr['title']} | {mr['state']} "
            f"| by {mr['author']['username']} | {mr['source_branch']} -> {mr['target_branch']}"
        )
    return "\n".join(lines) if lines else "No merge requests found."


async def create_project(name: str, namespace_id: int | None = None) -> str:
    """Create a new GitLab project.

    Args:
        name: Project name
        namespace_id: Optional namespace/group ID to create project in
    """
    payload: dict = {
        "name": name,
        "visibility": "internal",
        "initialize_with_readme": True,
    }
    if namespace_id:
        payload["namespace_id"] = namespace_id
    project = await _gitlab_post("/projects", json=payload)
    return (
        f"Created project: {project['path_with_namespace']}\n"
        f"URL: {project['web_url']}\n"
        f"SSH: {project['ssh_url_to_repo']}\n"
        f"HTTP: {project['http_url_to_repo']}\n"
        f"ID: {project['id']}"
    )
