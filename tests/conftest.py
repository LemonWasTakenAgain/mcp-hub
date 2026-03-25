"""Shared test fixtures."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    # Patch database to use in-memory approach
    with patch("mcp_hub.main.engine") as mock_engine, \
         patch("mcp_hub.main.get_session") as mock_get_session:

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(
            all=MagicMock(return_value=[]),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar=MagicMock(return_value=0),
        ))

        async def fake_session():
            yield mock_session

        mock_get_session.return_value = fake_session()

        from mcp_hub.main import app
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
