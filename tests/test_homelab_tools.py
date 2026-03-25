"""Test homelab tools."""

import pytest

from mcp_hub.tools.homelab_tools import check_service, system_info


@pytest.mark.asyncio
async def test_system_info():
    result = await system_info()
    assert "System Information" in result
    assert "Hostname" in result
    assert "Python" in result


@pytest.mark.asyncio
async def test_check_service_unreachable():
    result = await check_service("192.0.2.1", 99999)
    assert "unreachable" in result or "timed out" in result
