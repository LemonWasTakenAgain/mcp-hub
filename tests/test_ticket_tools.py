"""Test ticket queue tools with mocked database sessions."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.ticket import Ticket, TicketComment
from mcp_hub.tools.ticket_tools import (
    add_comment,
    create_ticket,
    get_ticket,
    list_denied,
    list_tickets,
    update_ticket,
)


def _make_ticket(**overrides) -> Ticket:
    """Create a Ticket instance with sensible defaults."""
    now = datetime.now(timezone.utc)
    defaults = {
        "id": 1,
        "title": "Fix DNS resolution",
        "description": "DNS is broken on VLAN 40",
        "from_role": "Dev Manager",
        "to_role": "Infra Worker",
        "priority": "medium",
        "status": "queued",
        "model_assigned": None,
        "triage_difficulty": None,
        "triage_reasoning": None,
        "denial_reason": None,
        "result": None,
        "created_at": now,
        "updated_at": now,
        "comments": [],
    }
    defaults.update(overrides)
    t = MagicMock(spec=Ticket)
    for k, v in defaults.items():
        setattr(t, k, v)
    return t


def _mock_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# -- create_ticket tests --


@pytest.mark.asyncio
async def test_create_ticket_success():
    ctx, session = _mock_session()

    async def fake_refresh(obj):
        obj.id = 42

    session.refresh = fake_refresh

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await create_ticket(
            "Fix DNS", "DNS broken on VLAN 40", "Dev Manager", "Infra Worker", "high"
        )
    assert "Ticket #42 created" in result
    assert "Fix DNS" in result
    assert "high" in result
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_ticket_invalid_role():
    result = await create_ticket("Fix DNS", "broken", "Nobody", "Infra Worker")
    assert "Error" in result
    assert "invalid from_role" in result


@pytest.mark.asyncio
async def test_create_ticket_invalid_priority():
    result = await create_ticket("Fix DNS", "broken", "Dev Manager", "Infra Worker", "urgent")
    assert "Error" in result
    assert "invalid priority" in result


@pytest.mark.asyncio
async def test_create_ticket_empty_title():
    result = await create_ticket("", "broken", "Dev Manager", "Infra Worker")
    assert "Error" in result
    assert "title" in result


@pytest.mark.asyncio
async def test_create_ticket_empty_description():
    result = await create_ticket("Fix DNS", "", "Dev Manager", "Infra Worker")
    assert "Error" in result
    assert "description" in result


# -- list_tickets tests --


@pytest.mark.asyncio
async def test_list_tickets_with_results():
    ctx, session = _mock_session()
    tickets = [_make_ticket(id=1), _make_ticket(id=2, title="Deploy app", priority="high")]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = tickets
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await list_tickets()
    assert "#1" in result
    assert "#2" in result
    assert "2 results" in result


@pytest.mark.asyncio
async def test_list_tickets_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await list_tickets(status="queued")
    assert "No tickets found" in result
    assert "status=queued" in result


@pytest.mark.asyncio
async def test_list_tickets_invalid_status():
    result = await list_tickets(status="invalid")
    assert "Error" in result
    assert "invalid status" in result


# -- get_ticket tests --


@pytest.mark.asyncio
async def test_get_ticket_found():
    ctx, session = _mock_session()
    comment = MagicMock(spec=TicketComment)
    comment.role = "Infra Worker"
    comment.content = "Working on it"
    comment.created_at = datetime.now(timezone.utc)

    ticket = _make_ticket(
        id=5,
        title="Fix DNS",
        description="DNS broken",
        result="Fixed in MR !42",
        comments=[comment],
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = ticket
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await get_ticket(5)
    assert "# Ticket #5" in result
    assert "Fix DNS" in result
    assert "Fixed in MR !42" in result
    assert "Working on it" in result


@pytest.mark.asyncio
async def test_get_ticket_not_found():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await get_ticket(999)
    assert "not found" in result


# -- update_ticket tests --


@pytest.mark.asyncio
async def test_update_ticket_status():
    ctx, session = _mock_session()
    ticket = _make_ticket(id=1, status="queued")
    session.get = AsyncMock(return_value=ticket)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await update_ticket(1, status="in_progress")
    assert "updated" in result
    assert "status → in_progress" in result
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_ticket_invalid_transition():
    ctx, session = _mock_session()
    ticket = _make_ticket(id=1, status="completed")
    session.get = AsyncMock(return_value=ticket)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await update_ticket(1, status="queued")
    assert "Error" in result
    assert "cannot transition" in result.lower()


@pytest.mark.asyncio
async def test_update_ticket_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await update_ticket(999, status="completed")
    assert "not found" in result


@pytest.mark.asyncio
async def test_update_ticket_with_result():
    ctx, session = _mock_session()
    ticket = _make_ticket(id=1, status="in_progress")
    session.get = AsyncMock(return_value=ticket)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await update_ticket(1, status="completed", result="Done, MR !5 merged")
    assert "status → completed" in result
    assert "result updated" in result


@pytest.mark.asyncio
async def test_update_ticket_no_fields():
    ctx, session = _mock_session()
    ticket = _make_ticket(id=1)
    session.get = AsyncMock(return_value=ticket)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await update_ticket(1)
    assert "Error" in result
    assert "no fields" in result


# -- add_comment tests --


@pytest.mark.asyncio
async def test_add_comment_success():
    ctx, session = _mock_session()
    ticket = _make_ticket(id=1)
    session.get = AsyncMock(return_value=ticket)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await add_comment(1, "Infra Worker", "Started working on this")
    assert "Comment added" in result
    assert "Infra Worker" in result
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_comment_empty():
    result = await add_comment(1, "Infra Worker", "   ")
    assert "Error" in result
    assert "empty" in result


@pytest.mark.asyncio
async def test_add_comment_ticket_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await add_comment(999, "Infra Worker", "hello")
    assert "not found" in result


# -- list_denied tests --


@pytest.mark.asyncio
async def test_list_denied_with_results():
    ctx, session = _mock_session()
    tickets = [
        _make_ticket(id=3, status="denied", denial_reason="Out of scope", title="Bad request"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = tickets
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await list_denied()
    assert "#3" in result
    assert "Out of scope" in result


@pytest.mark.asyncio
async def test_list_denied_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await list_denied(from_role="Dev Manager")
    assert "No denied tickets" in result
