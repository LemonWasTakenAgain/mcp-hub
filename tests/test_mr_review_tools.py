"""Test MR review tools with mocked database sessions."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.mr_review import MrReview
from mcp_hub.tools.mr_review_tools import claim_mr, get_review, list_reviews, my_mrs


def _make_review(**overrides) -> MrReview:
    """Create an MrReview instance with sensible defaults."""
    now = datetime.now(UTC)
    defaults = {
        "id": 1,
        "project_id": 10,
        "mr_iid": 31,
        "title": "Add ticket queue system",
        "source_branch": "feat/ticket-queue",
        "author_role": "Infra Worker",
        "pipeline_status": "success",
        "verdict": "pending",
        "reason": None,
        "details": None,
        "reviewer_model": None,
        "lines_changed": 150,
        "commit_sha": "abc12345",
        "mr_url": "https://gitlab.steelcanvas.studio/infrastructure/mcp-hub/-/merge_requests/31",
        "created_at": now,
        "updated_at": now,
        "reviewed_at": None,
        "merged_at": None,
    }
    defaults.update(overrides)
    review = MrReview()
    for k, v in defaults.items():
        setattr(review, k, v)
    return review


def _mock_session():
    """Create a mock async session context manager."""
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# -- list_reviews tests --


@pytest.mark.asyncio
async def test_list_reviews_empty():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await list_reviews()
    assert "No MR reviews found" in result


@pytest.mark.asyncio
async def test_list_reviews_with_results():
    cm, session = _mock_session()
    reviews = [
        _make_review(id=1, verdict="approved", title="Fix DNS"),
        _make_review(id=2, verdict="pending", title="Add logging"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = reviews
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await list_reviews()
    assert "MR Reviews (2 results)" in result
    assert "Fix DNS" in result
    assert "Add logging" in result


@pytest.mark.asyncio
async def test_list_reviews_with_filters():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await list_reviews(project_id=10, verdict="approved")
    assert "project=10" in result
    assert "verdict=approved" in result


@pytest.mark.asyncio
async def test_list_reviews_limit_clamped():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        # Limit should be clamped to 100
        result = await list_reviews(limit=999)
    assert "No MR reviews found" in result


# -- get_review tests --


@pytest.mark.asyncio
async def test_get_review_found():
    cm, session = _mock_session()
    review = _make_review(
        verdict="approved",
        reason="All checks pass",
        details="- Pipeline passed\n- Lint clean",
        reviewer_model="sonnet",
        reviewed_at=datetime.now(UTC),
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = review
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await get_review(10, 31)
    assert "MR Review: PID=10 !31" in result
    assert "approved" in result
    assert "All checks pass" in result
    assert "sonnet" in result


@pytest.mark.asyncio
async def test_get_review_not_found():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await get_review(99, 999)
    assert "No review found" in result


@pytest.mark.asyncio
async def test_get_review_with_merge_info():
    cm, session = _mock_session()
    review = _make_review(
        verdict="merged",
        merged_at=datetime.now(UTC),
        mr_url="https://gitlab.steelcanvas.studio/test/-/merge_requests/1",
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = review
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await get_review(10, 31)
    assert "Merged:" in result
    assert "URL:" in result


# -- my_mrs tests --


@pytest.mark.asyncio
async def test_my_mrs_empty():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await my_mrs("Infra Worker")
    assert "No open MRs for Infra Worker" in result


@pytest.mark.asyncio
async def test_my_mrs_with_results():
    cm, session = _mock_session()
    reviews = [
        _make_review(verdict="pending", title="Add health probes"),
        _make_review(id=2, verdict="rejected", title="Fix bug", reason="Lint failures"),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = reviews
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await my_mrs("Infra Worker")
    assert "Open MRs for Infra Worker" in result
    assert "Add health probes" in result
    assert "Fix bug" in result
    assert "Lint failures" in result


# -- claim_mr tests --


@pytest.mark.asyncio
async def test_claim_mr_success():
    cm, session = _mock_session()
    review = _make_review(author_role=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = review
    session.execute = AsyncMock(return_value=mock_result)
    session.commit = AsyncMock()

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await claim_mr(10, 31, "Dev Manager")
    assert "Claimed" in result
    assert "Dev Manager" in result
    assert review.author_role == "Dev Manager"


@pytest.mark.asyncio
async def test_claim_mr_not_found():
    cm, session = _mock_session()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    with patch("mcp_hub.tools.mr_review_tools.async_session", return_value=cm):
        result = await claim_mr(10, 999, "Dev Manager")
    assert "No review found" in result
    assert "retry" in result.lower()


@pytest.mark.asyncio
async def test_claim_mr_empty_role():
    with patch("mcp_hub.tools.mr_review_tools.async_session"):
        result = await claim_mr(10, 31, "")
    assert "Error" in result
    assert "author_role" in result
