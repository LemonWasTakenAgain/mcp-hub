"""Test ticket queue tools with mocked database sessions."""

from datetime import UTC, datetime
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


def _scalar_result(value):
    """Return a mock execute result whose scalar_one() returns value."""
    r = MagicMock()
    r.scalar_one.return_value = value
    return r


def _scalar_one_or_none_result(value):
    """Return a mock execute result whose scalar_one_or_none() returns value."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _passing_execute_side_effects(extra=None):
    """Side effects for session.execute that pass all three enforcement checks.

    Order: refile_count=0, dup=None, open_count=0, plus any extra results.
    """
    effects = [
        _scalar_result(0),  # refile count = 0
        _scalar_one_or_none_result(None),  # no duplicate ticket
        _scalar_result(0),  # open count = 0
    ]
    if extra:
        effects.extend(extra)
    return effects


def _make_ticket(**overrides) -> Ticket:
    """Create a Ticket instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "title": "Fix DNS resolution",
        "description": "DNS is broken on VLAN 40",
        "from_role": "Dev Manager",
        "to_role": "Infra Planner",
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
    session.add = MagicMock()  # session.add is sync on AsyncSession
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


# -- create_ticket tests --


@pytest.mark.asyncio
async def test_create_ticket_success():
    ctx, session = _mock_session()
    session.execute = AsyncMock(side_effect=_passing_execute_side_effects())

    async def fake_refresh(obj):
        obj.id = 42

    session.refresh = fake_refresh

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await create_ticket(
            "Fix DNS", "DNS broken on VLAN 40", "Dev Manager", "Infra Planner", "high"
        )
    assert "Ticket #42 created" in result
    assert "Fix DNS" in result
    assert "high" in result
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_ticket_invalid_role():
    result = await create_ticket("Fix DNS", "broken", "Nobody", "Infra Planner")
    assert "Error" in result
    assert "invalid from_role" in result


@pytest.mark.asyncio
async def test_create_ticket_invalid_priority():
    result = await create_ticket("Fix DNS", "broken", "Dev Manager", "Infra Planner", "urgent")
    assert "Error" in result
    assert "invalid priority" in result


@pytest.mark.asyncio
async def test_create_ticket_empty_title():
    result = await create_ticket("", "broken", "Dev Manager", "Infra Planner")
    assert "Error" in result
    assert "title" in result


@pytest.mark.asyncio
async def test_create_ticket_empty_description():
    result = await create_ticket("Fix DNS", "", "Dev Manager", "Infra Planner")
    assert "Error" in result
    assert "description" in result


# -- Enforcement: dedupe --


@pytest.mark.asyncio
async def test_create_ticket_dedupe_rejected():
    """ticket_create rejects a duplicate open ticket filed within the last 10 minutes."""
    ctx, session = _mock_session()
    existing = _make_ticket(id=7, title="Fix DNS", status="queued")
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(0),  # refile count = 0
            _scalar_one_or_none_result(existing),  # duplicate found
        ]
    )

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await create_ticket(
            "Fix DNS", "DNS broken on VLAN 40", "Dev Manager", "Infra Planner"
        )

    assert "duplicate" in result
    assert "#7" in result
    # One TicketLimit audit record added, ticket itself not added
    session.add.assert_called_once()
    added_obj = session.add.call_args[0][0]
    from mcp_hub.models.ticket import TicketLimit

    assert isinstance(added_obj, TicketLimit)
    assert added_obj.event_type == "dedupe"


# -- Enforcement: rate limit --


@pytest.mark.asyncio
async def test_create_ticket_rate_limit_rejected():
    """ticket_create rejects when from_role already has 10 open tickets."""
    ctx, session = _mock_session()
    oldest = _make_ticket(id=3, title="Some old ticket", status="queued")
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(0),  # refile count = 0
            _scalar_one_or_none_result(None),  # no duplicate
            _scalar_result(10),  # open count = 10 (at limit)
            _scalar_one_or_none_result(oldest),  # oldest open ticket
        ]
    )

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await create_ticket("New Task", "Something new", "Dev Manager", "Infra Planner")

    assert "rate_limited" in result
    assert "10" in result
    assert "#3" in result
    session.add.assert_called_once()
    added_obj = session.add.call_args[0][0]
    from mcp_hub.models.ticket import TicketLimit

    assert isinstance(added_obj, TicketLimit)
    assert added_obj.event_type == "rate_limit"


# -- Enforcement: refile cap --


@pytest.mark.asyncio
async def test_create_ticket_refile_cap_rejected():
    """ticket_create rejects a 3rd refile of the same title within 1 hour."""
    ctx, session = _mock_session()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(2),  # 2 existing tickets with same title in last hour → reject 3rd
        ]
    )

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await create_ticket("Fix DNS", "DNS broken again", "Dev Manager", "Infra Planner")

    assert "refile_cap" in result
    assert "2" in result
    assert "PR Manager" in result
    session.add.assert_called_once()
    added_obj = session.add.call_args[0][0]
    from mcp_hub.models.ticket import TicketLimit

    assert isinstance(added_obj, TicketLimit)
    assert added_obj.event_type == "refile_cap"


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
    comment.role = "Infra Planner"
    comment.content = "Working on it"
    comment.created_at = datetime.now(UTC)

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
        result = await add_comment(1, "Infra Planner", "Started working on this")
    assert "Comment added" in result
    assert "Infra Planner" in result
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_comment_empty():
    result = await add_comment(1, "Infra Planner", "   ")
    assert "Error" in result
    assert "empty" in result


@pytest.mark.asyncio
async def test_add_comment_ticket_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.ticket_tools.async_session", return_value=ctx):
        result = await add_comment(999, "Infra Planner", "hello")
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
