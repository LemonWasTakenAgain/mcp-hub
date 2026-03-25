"""Test proxy manager and connector."""

import asyncio

import pytest

from mcp_hub.proxy.env_resolver import check_server_ready, has_unresolved_vars, resolve_env_vars
from mcp_hub.proxy.registry import TransportType, UpstreamRegistry, UpstreamServer


def test_upstream_connection_status():
    """Test UpstreamConnection status reporting."""
    from mcp_hub.proxy.connector import UpstreamConnection

    server = UpstreamServer(
        name="test-server",
        transport=TransportType.STDIO,
        command="echo",
    )
    conn = UpstreamConnection(server=server)

    status = conn.status
    assert status["name"] == "test-server"
    assert status["connected"] is False
    assert status["tools"] == 0
    assert status["error"] is None


def test_manager_get_status_empty():
    """Test ProxyManager status with no connections."""
    from unittest.mock import MagicMock

    from mcp_hub.proxy.manager import ProxyManager

    registry = UpstreamRegistry()
    manager = ProxyManager(registry=registry, mcp_server=MagicMock())

    status = manager.get_status()
    assert status["total_servers"] == 0
    assert status["connected"] == 0
    assert status["total_proxied_tools"] == 0
    assert status["servers"] == []


def test_manager_get_tool_map_empty():
    """Test tool map when no tools are proxied."""
    from unittest.mock import MagicMock

    from mcp_hub.proxy.manager import ProxyManager

    registry = UpstreamRegistry()
    manager = ProxyManager(registry=registry, mcp_server=MagicMock())

    assert manager.get_tool_map() == {}


def test_check_server_ready_no_command():
    server = UpstreamServer(name="empty", transport=TransportType.STDIO, command="")
    ready, msg = check_server_ready(server)
    assert ready is False
    assert "No command" in msg


def test_check_server_ready_with_command():
    server = UpstreamServer(name="ok", transport=TransportType.STDIO, command="npx")
    ready, msg = check_server_ready(server)
    assert ready is True
    assert msg == "Ready"


def test_check_server_ready_empty_arg():
    server = UpstreamServer(
        name="bad-arg",
        transport=TransportType.STDIO,
        command="npx",
        args=["-y", ""],
    )
    ready, msg = check_server_ready(server)
    assert ready is False
    assert "Empty argument" in msg


def test_has_unresolved_vars():
    assert has_unresolved_vars("${FOO}") is True
    assert has_unresolved_vars("resolved_value") is False
    assert has_unresolved_vars("") is False


def test_reconnect_locks_created():
    """Verify reconnect locks dict is initialized."""
    from unittest.mock import MagicMock

    from mcp_hub.proxy.manager import ProxyManager

    registry = UpstreamRegistry()
    manager = ProxyManager(registry=registry, mcp_server=MagicMock())
    assert isinstance(manager._reconnect_locks, dict)
    assert len(manager._reconnect_locks) == 0
