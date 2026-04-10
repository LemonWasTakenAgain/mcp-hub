"""Test homelab tools."""

import json
import os
import time
from unittest.mock import patch

import pytest

from mcp_hub.tools.homelab_tools import (
    check_service,
    dispatcher_health,
    dns_lookup,
    http_check,
    ping_host,
    system_info,
)


@pytest.mark.asyncio
async def test_system_info():
    result = await system_info()
    assert "System Information" in result
    assert "Hostname" in result
    assert "Python" in result


@pytest.mark.asyncio
async def test_system_info_contains_disk():
    result = await system_info()
    assert "Disk" in result
    assert "GB" in result


@pytest.mark.asyncio
async def test_ping_valid_hostname():
    # Ping localhost — may raise FileNotFoundError in CI without ping binary
    try:
        result = await ping_host("127.0.0.1")
        assert "127.0.0.1" in result
    except FileNotFoundError:
        pytest.skip("ping binary not available in CI")


@pytest.mark.asyncio
async def test_ping_rejects_injection():
    result = await ping_host("8.8.8.8; rm -rf /")
    assert "Invalid host" in result


@pytest.mark.asyncio
async def test_ping_rejects_pipe():
    result = await ping_host("8.8.8.8 | cat /etc/passwd")
    assert "Invalid host" in result


@pytest.mark.asyncio
async def test_ping_rejects_backtick():
    result = await ping_host("`whoami`")
    assert "Invalid host" in result


@pytest.mark.asyncio
async def test_check_service_unreachable():
    result = await check_service("192.0.2.1", 99999)
    assert "unreachable" in result or "timed out" in result or "Invalid" in result


@pytest.mark.asyncio
async def test_check_service_rejects_bad_port():
    result = await check_service("localhost", 0)
    assert "Invalid" in result


@pytest.mark.asyncio
async def test_check_service_rejects_bad_host():
    result = await check_service("host;injection", 80)
    assert "Invalid" in result


@pytest.mark.asyncio
async def test_dns_lookup_rejects_injection():
    result = await dns_lookup("example.com; cat /etc/passwd")
    assert "Invalid hostname" in result


@pytest.mark.asyncio
async def test_http_check_rejects_ftp():
    result = await http_check("ftp://evil.com")
    assert "Invalid URL" in result


@pytest.mark.asyncio
async def test_http_check_rejects_empty():
    result = await http_check("")
    assert "Invalid URL" in result


@pytest.mark.asyncio
async def test_http_check_rejects_javascript():
    result = await http_check("javascript:alert(1)")
    assert "Invalid URL" in result


@pytest.mark.asyncio
async def test_http_check_allows_private_ip():
    """http_check must accept RFC1918 addresses (it targets internal homelab endpoints)."""
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.reason_phrase = "OK"
    mock_response.headers = {"content-type": "text/html"}
    mock_response.content = b"<html></html>"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await http_check("http://192.168.1.1")

    assert "Invalid URL" not in result
    assert "192.168.1.1" in result


@pytest.mark.asyncio
async def test_dispatcher_health_missing_files(tmp_path):
    """Missing heartbeat files should return unhealthy status."""
    import mcp_hub.tools.homelab_tools as ht

    with patch.object(ht, "_HEARTBEAT_DIR", tmp_path):
        result_str = await dispatcher_health()

    result = json.loads(result_str)
    assert result["status"] == "unhealthy"
    assert result["dispatcher"]["healthy"] is False
    assert result["dispatcher"]["last_heartbeat"] == "never"
    assert result["monitor"]["healthy"] is False
    assert result["monitor"]["last_heartbeat"] == "never"


@pytest.mark.asyncio
async def test_dispatcher_health_fresh_files(tmp_path):
    """Fresh heartbeat files within thresholds should return healthy."""
    ts = "2026-04-10T12:00:00Z"
    (tmp_path / "heartbeat-dispatcher").write_text(ts)
    (tmp_path / "heartbeat-monitor").write_text(ts)

    import mcp_hub.tools.homelab_tools as ht

    with patch.object(ht, "_HEARTBEAT_DIR", tmp_path):
        result_str = await dispatcher_health()

    result = json.loads(result_str)
    assert result["status"] == "healthy"
    assert result["dispatcher"]["healthy"] is True
    assert result["dispatcher"]["last_heartbeat"] == ts
    assert result["monitor"]["healthy"] is True
    assert result["dispatcher"]["threshold_seconds"] == 300
    assert result["monitor"]["threshold_seconds"] == 360


@pytest.mark.asyncio
async def test_dispatcher_health_stale_dispatcher(tmp_path):
    """Stale dispatcher heartbeat (mtime > 300s ago) should report unhealthy."""
    dispatcher_hb = tmp_path / "heartbeat-dispatcher"
    monitor_hb = tmp_path / "heartbeat-monitor"
    dispatcher_hb.write_text("2026-04-10T11:00:00Z")
    monitor_hb.write_text("2026-04-10T12:00:00Z")

    stale_mtime = time.time() - 400
    os.utime(dispatcher_hb, (stale_mtime, stale_mtime))

    import mcp_hub.tools.homelab_tools as ht

    with patch.object(ht, "_HEARTBEAT_DIR", tmp_path):
        result_str = await dispatcher_health()

    result = json.loads(result_str)
    assert result["status"] == "unhealthy"
    assert result["dispatcher"]["healthy"] is False
    assert result["dispatcher"]["age_seconds"] >= 400
    assert result["monitor"]["healthy"] is True


@pytest.mark.asyncio
async def test_dispatcher_health_json_structure(tmp_path):
    """Result must parse as JSON and contain all required keys."""
    import mcp_hub.tools.homelab_tools as ht

    with patch.object(ht, "_HEARTBEAT_DIR", tmp_path):
        result_str = await dispatcher_health()

    result = json.loads(result_str)
    assert "status" in result
    assert "dispatcher" in result
    assert "monitor" in result
    for key in ("healthy", "last_heartbeat", "age_seconds", "threshold_seconds"):
        assert key in result["dispatcher"]
        assert key in result["monitor"]
