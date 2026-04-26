"""Test solution pattern tools with mocked database sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from mcp_hub.models.solution_pattern import VALID_OUTCOMES, SolutionPattern
from mcp_hub.tools.solution_pattern_tools import (
    aggregate_patterns,
    create_pattern,
    list_patterns,
)


def _make_pattern(**overrides) -> SolutionPattern:
    """Create a SolutionPattern instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "ticket_id": 42,
        "agent_role": "Dev Manager",
        "model_assigned": "claude-sonnet-4-6",
        "duration_seconds": 300,
        "tool_calls": 25,
        "unique_tool_calls": 10,
        "retries": 1,
        "errors": 2,
        "mr_iid": 55,
        "mr_pipeline_runs": 2,
        "freeze_gaps_count": 0,
        "freeze_gaps_total_seconds": 0,
        "estimated_cost_usd": 0.0120,
        "outcome": "completed",
        "notes": None,
        "created_at": now,
    }
    defaults.update(overrides)
    sp = SolutionPattern()
    for k, v in defaults.items():
        setattr(sp, k, v)
    return sp


def _mock_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# -- VALID_OUTCOMES sanity check --


def test_valid_outcomes_contains_expected():
    assert VALID_OUTCOMES == {"completed", "denied", "blocked", "needs_human"}


# -- create_pattern tests --


@pytest.mark.asyncio
async def test_create_pattern_success():
    cm, session = _mock_session()

    # After commit + refresh the session will have `pattern` as result
    async def fake_refresh(obj):
        obj.id = 7
        obj.created_at = datetime.now(UTC)

    session.refresh = AsyncMock(side_effect=fake_refresh)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await create_pattern(
            ticket_id=99,
            agent_role="Dev Manager",
            duration_seconds=300,
            outcome="completed",
            model_assigned="claude-sonnet-4-6",
            tool_calls=25,
            unique_tool_calls=10,
            retries=1,
            errors=2,
            mr_iid=55,
            mr_pipeline_runs=2,
            estimated_cost_usd=0.012,
            notes="test note",
        )

    assert "SolutionPattern #7 recorded for ticket #99" == result
    session.add.assert_called_once()
    session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_pattern_invalid_outcome():
    result = await create_pattern(
        ticket_id=1,
        agent_role="Dev Manager",
        duration_seconds=100,
        outcome="invalid_outcome",
    )
    assert "Error: invalid outcome 'invalid_outcome'" in result
    assert "completed" in result


# -- list_patterns tests --


@pytest.mark.asyncio
async def test_list_patterns_empty():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await list_patterns()
    assert "No solution patterns found" in result


@pytest.mark.asyncio
async def test_list_patterns_with_results():
    cm, session = _mock_session()
    patterns = [
        _make_pattern(id=1, ticket_id=10, outcome="completed", agent_role="Dev Manager"),
        _make_pattern(id=2, ticket_id=11, outcome="denied", agent_role="Infra Planner"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = patterns
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await list_patterns()
    assert "Solution Patterns (2 results)" in result
    assert "Dev Manager" in result
    assert "Infra Planner" in result
    assert "ticket=10" in result


@pytest.mark.asyncio
async def test_list_patterns_agent_role_filter_empty():
    """Filter by agent_role returns empty with filter hint in message."""
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await list_patterns(agent_role="Infra Planner")
    assert "No solution patterns found" in result
    assert "role=Infra Planner" in result


@pytest.mark.asyncio
async def test_list_patterns_invalid_since():
    result = await list_patterns(since="not-a-date")
    assert "Error: invalid since date" in result


@pytest.mark.asyncio
async def test_list_patterns_invalid_outcome():
    result = await list_patterns(outcome="bogus")
    assert "Error: invalid outcome" in result


# -- aggregate_patterns tests --


@pytest.mark.asyncio
async def test_aggregate_patterns_invalid_group_by():
    result = await aggregate_patterns(group_by="invalid")
    assert "Error: invalid group_by 'invalid'" in result


@pytest.mark.asyncio
async def test_aggregate_patterns_empty():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await aggregate_patterns(group_by="role")
    assert "No solution patterns found" in result


@pytest.mark.asyncio
async def test_aggregate_patterns_valid_group_by():
    cm, session = _mock_session()

    # Build a mock row with named attributes
    row = MagicMock()
    row.group_value = "Dev Manager"
    row.count = 5
    row.avg_duration = 250.0
    row.max_duration = 400
    row.avg_tool_calls = 20.0
    row.avg_errors = 1.0
    row.avg_pipeline_runs = 1.5

    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await aggregate_patterns(group_by="role")
    assert "Solution Pattern Aggregates" in result
    assert "group_by=role" in result
    assert "Dev Manager" in result
    assert "250.0" in result


@pytest.mark.asyncio
async def test_aggregate_patterns_by_outcome():
    cm, session = _mock_session()

    row = MagicMock()
    row.group_value = "completed"
    row.count = 10
    row.avg_duration = 180.0
    row.max_duration = 500
    row.avg_tool_calls = 15.0
    row.avg_errors = 0.5
    row.avg_pipeline_runs = 1.0

    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.solution_pattern_tools.async_session", return_value=cm):
        result = await aggregate_patterns(group_by="outcome")
    assert "group_by=outcome" in result
    assert "completed" in result


# -- REST endpoint tests --


@pytest.fixture
async def sp_client():
    """Async HTTP client with mocked DB session for solution-patterns endpoints."""
    from mcp_hub.database import get_session
    from mcp_hub.main import app

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            all=MagicMock(return_value=[]),
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))),
            scalar=MagicMock(return_value=0),
        )
    )

    async def override_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_session
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.asyncio
async def test_rest_list_solution_patterns_empty(sp_client):
    client, session = sp_client
    resp = await client.get("/api/solution-patterns")
    assert resp.status_code == 200
    data = resp.json()
    assert "patterns" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_rest_create_solution_pattern_missing_field(sp_client):
    client, session = sp_client
    resp = await client.post(
        "/api/solution-patterns",
        json={"ticket_id": 1, "agent_role": "Dev Manager", "duration_seconds": 100},
    )
    assert resp.status_code == 400
    assert "Missing required field: outcome" in resp.json()["error"]


@pytest.mark.asyncio
async def test_rest_create_solution_pattern_invalid_outcome(sp_client):
    client, session = sp_client
    resp = await client.post(
        "/api/solution-patterns",
        json={
            "ticket_id": 1,
            "agent_role": "Dev Manager",
            "duration_seconds": 100,
            "outcome": "not_valid",
        },
    )
    assert resp.status_code == 400
    assert "Invalid outcome" in resp.json()["error"]


@pytest.mark.asyncio
async def test_rest_create_solution_pattern_success(sp_client):
    client, session = sp_client

    # Mock refresh to populate id and created_at on the object
    now = datetime.now(UTC)

    async def fake_refresh(obj):
        obj.id = 5
        obj.ticket_id = 42
        obj.created_at = now

    session.refresh = AsyncMock(side_effect=fake_refresh)

    resp = await client.post(
        "/api/solution-patterns",
        json={
            "ticket_id": 42,
            "agent_role": "Dev Manager",
            "duration_seconds": 250,
            "outcome": "completed",
            "tool_calls": 20,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 5
    assert data["ticket_id"] == 42
    assert "created_at" in data


@pytest.mark.asyncio
async def test_rest_aggregate_invalid_group_by(sp_client):
    client, _ = sp_client
    resp = await client.get("/api/solution-patterns/aggregate?group_by=bogus")
    assert resp.status_code == 400
    assert "Invalid group_by" in resp.json()["error"]


@pytest.mark.asyncio
async def test_rest_aggregate_valid(sp_client):
    client, session = sp_client
    # aggregate endpoint queries rows via .all() not .scalars()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    resp = await client.get("/api/solution-patterns/aggregate?group_by=role")
    assert resp.status_code == 200
    data = resp.json()
    assert data["group_by"] == "role"
    assert "aggregates" in data
