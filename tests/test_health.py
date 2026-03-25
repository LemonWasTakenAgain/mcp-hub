"""Test health and API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_hub.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "0.1.0"
    assert "mcp_tools" in data


@pytest.mark.asyncio
async def test_list_tools(client):
    resp = await client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "homelab_system_info" in tool_names
    assert "gitlab_list_projects" in tool_names
    assert "k8s_cluster_status" in tool_names
