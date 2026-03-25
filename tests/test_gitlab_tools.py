"""Test GitLab tools with mocked HTTP client."""

from unittest.mock import AsyncMock, patch

import pytest

from mcp_hub.tools.gitlab_tools import (
    create_project,
    get_pipeline_jobs,
    get_project_pipelines,
    list_merge_requests,
    list_projects,
)


def _mock_response(json_data, status_code=200):
    resp = AsyncMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = AsyncMock()
    return resp


@pytest.fixture
def mock_httpx():
    with patch("mcp_hub.tools.gitlab_tools.httpx.AsyncClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
        yield client


@pytest.mark.asyncio
async def test_list_projects_with_results(mock_httpx):
    mock_httpx.get.return_value = _mock_response([
        {
            "path_with_namespace": "infra/mcp-hub",
            "web_url": "http://gitlab.local/infra/mcp-hub",
            "last_activity_at": "2026-03-25T12:00:00Z",
            "star_count": 0,
        }
    ])
    result = await list_projects()
    assert "infra/mcp-hub" in result


@pytest.mark.asyncio
async def test_list_projects_empty(mock_httpx):
    mock_httpx.get.return_value = _mock_response([])
    result = await list_projects()
    assert "No projects found" in result


@pytest.mark.asyncio
async def test_list_projects_with_search(mock_httpx):
    mock_httpx.get.return_value = _mock_response([])
    await list_projects(search="test", per_page=5)
    call_args = mock_httpx.get.call_args[0][0]
    assert "search=test" in call_args
    assert "per_page=5" in call_args


@pytest.mark.asyncio
async def test_get_pipelines(mock_httpx):
    mock_httpx.get.return_value = _mock_response([
        {
            "id": 42,
            "status": "success",
            "ref": "main",
            "created_at": "2026-03-25T12:00:00Z",
        }
    ])
    result = await get_project_pipelines(10)
    assert "#42" in result
    assert "success" in result


@pytest.mark.asyncio
async def test_get_pipelines_empty(mock_httpx):
    mock_httpx.get.return_value = _mock_response([])
    result = await get_project_pipelines(10)
    assert "No pipelines found" in result


@pytest.mark.asyncio
async def test_get_pipeline_jobs(mock_httpx):
    mock_httpx.get.return_value = _mock_response([
        {
            "name": "lint:ruff",
            "status": "success",
            "stage": "lint",
            "duration": 12.5,
        }
    ])
    result = await get_pipeline_jobs(10, 42)
    assert "lint:ruff" in result
    assert "12.5s" in result


@pytest.mark.asyncio
async def test_list_merge_requests(mock_httpx):
    mock_httpx.get.return_value = _mock_response([
        {
            "iid": 1,
            "title": "Fix bug",
            "state": "opened",
            "author": {"username": "lemon"},
            "source_branch": "fix-bug",
            "target_branch": "main",
        }
    ])
    result = await list_merge_requests(10)
    assert "Fix bug" in result
    assert "lemon" in result


@pytest.mark.asyncio
async def test_create_project(mock_httpx):
    mock_httpx.post.return_value = _mock_response({
        "path_with_namespace": "infra/new-project",
        "web_url": "http://gitlab.local/infra/new-project",
        "ssh_url_to_repo": "git@gitlab.local:infra/new-project.git",
        "http_url_to_repo": "http://gitlab.local/infra/new-project.git",
        "id": 99,
    })
    result = await create_project("new-project", namespace_id=2)
    assert "infra/new-project" in result
    assert "99" in result
