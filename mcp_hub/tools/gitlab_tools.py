"""GitLab integration tools for MCP."""

import asyncio
import logging
from typing import Any, cast

import httpx

from mcp_hub.config import settings

logger = logging.getLogger("mcp_hub.gitlab")

_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0


async def _gitlab_request(
    method: str, path: str, *, json: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """Make an authenticated request to the GitLab API with retry logic."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            async with httpx.AsyncClient(
                base_url=settings.gitlab_url,
                headers={"PRIVATE-TOKEN": settings.gitlab_token},
                timeout=30.0,
            ) as client:
                resp = await client.request(method, f"/api/v4{path}", json=json)
                resp.raise_for_status()
                return cast(dict[str, Any] | list[Any], resp.json())
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as e:
            last_exc = e
            if attempt < _MAX_RETRIES - 1:
                delay = _RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    "GitLab %s %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    method,
                    path,
                    attempt + 1,
                    _MAX_RETRIES,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (502, 503, 504) and attempt < _MAX_RETRIES - 1:
                last_exc = e
                delay = _RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    "GitLab %s %s returned %d (attempt %d/%d) — retrying in %.1fs",
                    method,
                    path,
                    e.response.status_code,
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
    raise last_exc  # type: ignore[misc]


async def _gitlab_get(path: str) -> dict[str, Any] | list[Any]:
    """Make an authenticated GET request to the GitLab API."""
    return await _gitlab_request("GET", path)


async def _gitlab_post(path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make an authenticated POST request to the GitLab API."""
    result = await _gitlab_request("POST", path, json=json)
    return result  # type: ignore[return-value]


async def list_projects(search: str = "", per_page: int = 20) -> str:
    """List GitLab projects, optionally filtered by search term.

    Args:
        search: Optional search query to filter projects
        per_page: Number of results to return (default 20, max 100)
    """
    params = f"?per_page={min(per_page, 100)}&order_by=updated_at"
    if search:
        params += f"&search={search}"
    projects = cast(list[Any], await _gitlab_get(f"/projects{params}"))
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
    url = f"/projects/{project_id}/pipelines?per_page={min(per_page, 50)}"
    pipelines = cast(list[Any], await _gitlab_get(url))
    lines = []
    for p in pipelines:
        lines.append(
            f"- Pipeline #{p['id']} | {p['status']} | ref: {p['ref']} | {p['created_at'][:19]}"
        )
    return "\n".join(lines) if lines else "No pipelines found."


async def get_pipeline_jobs(project_id: int, pipeline_id: int) -> str:
    """Get jobs for a specific pipeline.

    Args:
        project_id: The GitLab project ID
        pipeline_id: The pipeline ID
    """
    jobs = cast(
        list[Any], await _gitlab_get(f"/projects/{project_id}/pipelines/{pipeline_id}/jobs")
    )
    lines = []
    for j in jobs:
        duration = f"{j.get('duration', 0):.1f}s" if j.get("duration") else "n/a"
        lines.append(f"- {j['name']} | {j['status']} | stage: {j['stage']} | duration: {duration}")
    return "\n".join(lines) if lines else "No jobs found."


async def list_merge_requests(project_id: int, state: str = "opened", per_page: int = 10) -> str:
    """List merge requests for a GitLab project.

    Args:
        project_id: The GitLab project ID
        state: MR state filter (opened, closed, merged, all)
        per_page: Number of results (default 10)
    """
    mrs = cast(
        list[Any],
        await _gitlab_get(
            f"/projects/{project_id}/merge_requests?state={state}&per_page={min(per_page, 50)}"
        ),
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
    payload: dict[str, Any] = {
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
