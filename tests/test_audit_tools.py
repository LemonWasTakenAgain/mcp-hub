"""Tests for audit trail tools."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.audit_log import AuditLog
from mcp_hub.tools.audit_tools import mr_review_history, ticket_history


def _make_audit_entry(**overrides):
    defaults = {
        "id": 1,
        "entity_type": "ticket",
        "entity_id": 1,
        "from_status": "queued",
        "to_status": "in_progress",
        "changed_by": "api",
        "reason": None,
        "changed_at": datetime(2026, 4, 10, 12, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    entry = MagicMock(spec=AuditLog)
    for k, v in defaults.items():
        setattr(entry, k, v)
    return entry


def _mock_session():
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


@pytest.mark.asyncio
async def test_ticket_history_with_entries():
    ctx, session = _mock_session()
    entry = _make_audit_entry()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[entry])))
        )
    )
    with patch("mcp_hub.tools.audit_tools.async_session", return_value=ctx):
        result = await ticket_history(1)
    assert "Audit trail for ticket #1" in result
    assert "queued → in_progress" in result
    assert "by api" in result


@pytest.mark.asyncio
async def test_ticket_history_no_entries():
    ctx, session = _mock_session()
    session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    with patch("mcp_hub.tools.audit_tools.async_session", return_value=ctx):
        result = await ticket_history(999)
    assert "No audit history" in result


@pytest.mark.asyncio
async def test_mr_review_history_no_review():
    ctx, session = _mock_session()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    with patch("mcp_hub.tools.audit_tools.async_session", return_value=ctx):
        result = await mr_review_history(10, 99)
    assert "No review record found" in result
