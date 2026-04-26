"""Test improvement tools with mocked database sessions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.improvement import Improvement, ImprovementComment
from mcp_hub.tools.improvement_tools import (
    add_comment,
    create_improvement,
    get_improvement,
    list_improvements,
    update_improvement,
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


def _mock_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    session.add = MagicMock()  # session.add is sync on AsyncSession
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


def _make_improvement(**overrides) -> Improvement:
    """Create an Improvement instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "agent_role": "Dev Manager",
        "category": "prompt",
        "severity": "minor",
        "status": "open",
        "title": "Tool X is too slow",
        "description": "Every call to tool X takes 5s, expected <1s",
        "related_ticket_id": None,
        "comments_count": 0,
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "comments": [],
    }
    defaults.update(overrides)
    i = MagicMock(spec=Improvement)
    for k, v in defaults.items():
        setattr(i, k, v)
    return i


# -- create_improvement tests --


@pytest.mark.asyncio
async def test_create_improvement_success():
    ctx, session = _mock_session()
    # No dedupe match — session.execute returns None for the dedupe query
    session.execute = AsyncMock(return_value=_scalar_one_or_none_result(None))
    session.flush = AsyncMock()

    # Track what gets added to the session
    added_objects: list = []
    session.add = MagicMock(side_effect=added_objects.append)

    # After flush, set id on the improvement (simulate DB auto-increment)
    async def fake_flush():
        for obj in added_objects:
            if not hasattr(obj, "id") or obj.id is None:
                obj.id = 7

    session.flush = fake_flush

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await create_improvement(
            "Dev Manager",
            "prompt",
            "minor",
            "Tool X is too slow",
            "Every call to tool X takes 5s",
        )

    assert "Improvement" in result and "created" in result
    assert "BLOCKER" not in result
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_improvement_invalid_role():
    result = await create_improvement("Nobody", "prompt", "minor", "Title", "Desc")
    assert "Error" in result
    assert "invalid agent_role" in result


@pytest.mark.asyncio
async def test_create_improvement_invalid_category():
    result = await create_improvement("Dev Manager", "badcat", "minor", "Title", "Desc")
    assert "Error" in result
    assert "invalid category" in result


@pytest.mark.asyncio
async def test_create_improvement_invalid_severity():
    result = await create_improvement("Dev Manager", "prompt", "critical", "Title", "Desc")
    assert "Error" in result
    assert "invalid severity" in result


@pytest.mark.asyncio
async def test_create_improvement_empty_title():
    result = await create_improvement("Dev Manager", "prompt", "minor", "   ", "Desc")
    assert "Error" in result
    assert "title" in result


@pytest.mark.asyncio
async def test_create_improvement_empty_description():
    result = await create_improvement("Dev Manager", "prompt", "minor", "Title", "   ")
    assert "Error" in result
    assert "description" in result


@pytest.mark.asyncio
async def test_create_improvement_title_too_long():
    long_title = "x" * 256
    result = await create_improvement("Dev Manager", "prompt", "minor", long_title, "Desc")
    assert "Error" in result
    assert "title too long" in result


@pytest.mark.asyncio
async def test_create_improvement_description_too_long():
    long_desc = "x" * 8193
    result = await create_improvement("Dev Manager", "prompt", "minor", "Title", long_desc)
    assert "Error" in result
    assert "description too long" in result


@pytest.mark.asyncio
async def test_create_improvement_dedupe_suggests_comment():
    ctx, session = _mock_session()
    existing = _make_improvement(id=3, title="Tool X is too slow right now")
    session.execute = AsyncMock(return_value=_scalar_one_or_none_result(existing))

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await create_improvement(
            "Dev Manager",
            "prompt",
            "minor",
            "Tool X is too slow",
            "Duplicate description",
        )

    assert "#3" in result
    assert "comment" in result.lower()


@pytest.mark.asyncio
async def test_create_improvement_blocker_auto_creates_ticket():
    ctx, session = _mock_session()
    session.execute = AsyncMock(return_value=_scalar_one_or_none_result(None))

    added_objects: list = []
    session.add = MagicMock(side_effect=added_objects.append)

    flush_call_count = 0

    async def fake_flush():
        nonlocal flush_call_count
        flush_call_count += 1
        # First flush: assign improvement.id = 5
        # Second flush: assign ticket.id = 99
        for i, obj in enumerate(added_objects):
            if not hasattr(obj, "_mock_id_set"):
                if isinstance(obj, Improvement):
                    obj.id = 5
                    obj._mock_id_set = True  # type: ignore[attr-defined]
                else:
                    # The Ticket object
                    obj.id = 99
                    obj._mock_id_set = True  # type: ignore[attr-defined]

    session.flush = fake_flush

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await create_improvement(
            "Dev Manager",
            "prompt",
            "blocker",
            "Critical tool failure",
            "This blocks all work",
        )

    assert "BLOCKER" in result
    assert "Ticket #" in result
    session.commit.assert_awaited_once()


# -- list_improvements tests --


@pytest.mark.asyncio
async def test_list_improvements_with_results():
    ctx, session = _mock_session()
    improvements = [
        _make_improvement(id=1),
        _make_improvement(id=2, title="Another issue", severity="major"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = improvements
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await list_improvements()
    assert "#1" in result
    assert "#2" in result
    assert "2 results" in result


@pytest.mark.asyncio
async def test_list_improvements_empty():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await list_improvements(status="resolved")
    assert "No improvements found" in result
    assert "status=resolved" in result


@pytest.mark.asyncio
async def test_list_improvements_invalid_status():
    result = await list_improvements(status="badstatus")
    assert "Error" in result
    assert "invalid status" in result


# -- get_improvement tests --


@pytest.mark.asyncio
async def test_get_improvement_found():
    ctx, session = _mock_session()
    comment = MagicMock(spec=ImprovementComment)
    comment.role = "Infra Planner"
    comment.content = "Confirmed, this is slow"
    comment.created_at = datetime.now(UTC)

    improvement = _make_improvement(
        id=5,
        title="Tool X is slow",
        description="Every call takes 5s",
        comments=[comment],
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = improvement
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await get_improvement(5)
    assert "# Improvement #5" in result
    assert "Tool X is slow" in result
    assert "Every call takes 5s" in result
    assert "Confirmed, this is slow" in result


@pytest.mark.asyncio
async def test_get_improvement_not_found():
    ctx, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await get_improvement(999)
    assert "not found" in result


# -- add_comment tests --


@pytest.mark.asyncio
async def test_improvement_comment_success():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1, comments_count=0)
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await add_comment(1, "Infra Planner", "Confirmed this is a real issue")
    assert "Comment added" in result
    assert "Infra Planner" in result
    assert improvement.comments_count == 1
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_improvement_comment_empty():
    result = await add_comment(1, "Infra Planner", "   ")
    assert "Error" in result
    assert "empty" in result


@pytest.mark.asyncio
async def test_improvement_comment_not_found():
    ctx, session = _mock_session()
    session.get = AsyncMock(return_value=None)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await add_comment(999, "Infra Planner", "hello")
    assert "not found" in result


# -- update_improvement tests --


@pytest.mark.asyncio
async def test_improvement_update_status():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1, status="open")
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await update_improvement(1, status="triaged")
    assert "updated" in result
    assert "status → triaged" in result
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_improvement_update_invalid_transition():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1, status="resolved")
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await update_improvement(1, status="open")
    assert "Error" in result
    assert "cannot transition" in result.lower()


@pytest.mark.asyncio
async def test_improvement_update_resolved_sets_timestamp():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1, status="accepted", resolved_at=None)
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await update_improvement(1, status="resolved")
    assert "status → resolved" in result
    assert improvement.resolved_at is not None


@pytest.mark.asyncio
async def test_improvement_update_severity():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1, severity="minor")
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await update_improvement(1, severity="major")
    assert "updated" in result
    assert "severity → major" in result
    assert improvement.severity == "major"


@pytest.mark.asyncio
async def test_improvement_update_no_fields():
    ctx, session = _mock_session()
    improvement = _make_improvement(id=1)
    session.get = AsyncMock(return_value=improvement)

    with patch("mcp_hub.tools.improvement_tools.async_session", return_value=ctx):
        result = await update_improvement(1)
    assert "Error" in result
    assert "no fields" in result
