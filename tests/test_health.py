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
async def test_healthz_endpoint(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    # May be 200 (healthy) or 503 (degraded) depending on DB/proxy state
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert data["version"] == "0.2.0"
    assert "mcp_tools" in data
    assert data["status"] in ("healthy", "degraded")


@pytest.mark.asyncio
async def test_list_tools(client):
    resp = await client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert "total" in data
    tool_names = [t["name"] for t in data["tools"]]
    assert "homelab_system_info" in tool_names
    assert "gitlab_list_projects" in tool_names
    assert "k8s_cluster_status" in tool_names


@pytest.mark.asyncio
async def test_list_tools_have_source(client):
    resp = await client.get("/api/tools")
    data = resp.json()
    for tool in data["tools"]:
        assert "source" in tool
        assert "name" in tool
        assert "description" in tool


@pytest.mark.asyncio
async def test_proxy_status_endpoint(client):
    resp = await client.get("/api/proxy/status")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_proxy_tools_endpoint(client):
    resp = await client.get("/api/proxy/tools")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_metrics_endpoint(client):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"mcp_hub_tools_registered_total" in resp.content
