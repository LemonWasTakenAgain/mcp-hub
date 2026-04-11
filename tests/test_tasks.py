"""Regression tests for audit-log-lifecycle bugs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_hub.models.mr_review import MrReview
from mcp_hub.tasks import _orphan_review_sweep, _sha_drift_reset, _stale_ticket_sweep


def _make_ticket(**overrides):
    defaults = {
        "id": 1,
        "title": "Test ticket",
        "status": "in_progress",
        "updated_at": datetime.now(UTC) - timedelta(hours=48),
        "model_assigned": "sonnet",
        "to_role": "Dev Manager",
    }
    defaults.update(overrides)
    ticket = MagicMock()
    for k, v in defaults.items():
        setattr(ticket, k, v)
    return ticket


def _make_review(**overrides):
    defaults = {
        "id": 1,
        "project_id": 10,
        "mr_iid": 42,
        "verdict": "approved",
        "merged_at": None,
        "updated_at": datetime.now(UTC) - timedelta(days=14),
    }
    defaults.update(overrides)
    review = MagicMock()
    for k, v in defaults.items():
        setattr(review, k, v)
    return review


def _mock_session():
    session = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


class TestStaleTicketSweepDedup:
    """Bug #2: _stale_ticket_sweep must not create duplicate triage tickets."""

    @pytest.mark.asyncio
    async def test_no_duplicate_triage_when_existing(self):
        ctx, session = _mock_session()
        stale_ticket = _make_ticket(id=99)

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [stale_ticket]

        existing_triage = _make_ticket(id=200, title="Stale ticket triage: #99")
        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none.return_value = existing_triage

        session.execute = AsyncMock(side_effect=[stale_result, dedup_result])

        with patch("mcp_hub.tasks.async_session", return_value=ctx):
            await _stale_ticket_sweep()

        added_objects = [call.args[0] for call in session.add.call_args_list]
        ticket_titles = [
            obj.title
            for obj in added_objects
            if hasattr(obj, "title") and "triage" in str(getattr(obj, "title", "")).lower()
        ]
        assert len(ticket_titles) == 0, "Should not create triage ticket when one already exists"

    @pytest.mark.asyncio
    async def test_creates_triage_when_none_exists(self):
        ctx, session = _mock_session()
        stale_ticket = _make_ticket(id=50)

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [stale_ticket]

        dedup_result = MagicMock()
        dedup_result.scalar_one_or_none.return_value = None

        session.execute = AsyncMock(side_effect=[stale_result, dedup_result])

        with patch("mcp_hub.tasks.async_session", return_value=ctx):
            await _stale_ticket_sweep()

        assert session.add.call_count == 2  # triage ticket + comment
        assert session.commit.called


class TestOrphanReviewSweep:
    """Bug #3: _orphan_review_sweep must use 'closed' for abandoned MRs, not 'merged'."""

    @pytest.mark.asyncio
    async def test_closed_mr_gets_closed_verdict(self):
        ctx, session = _mock_session()
        review = _make_review(id=5, verdict="approved")
        db_review = _make_review(id=5, verdict="approved")

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [review]

        session.execute = AsyncMock(return_value=stale_result)
        session.get = AsyncMock(return_value=db_review)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"state": "closed"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _orphan_review_sweep()

        assert db_review.verdict == "closed", "Closed MR must get 'closed' verdict, not 'merged'"
        assert db_review.merged_at is None, "merged_at should not be set for closed MRs"

    @pytest.mark.asyncio
    async def test_merged_mr_gets_merged_verdict(self):
        ctx, session = _mock_session()
        review = _make_review(id=6, verdict="pending")
        db_review = _make_review(id=6, verdict="pending")

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [review]

        session.execute = AsyncMock(return_value=stale_result)
        session.get = AsyncMock(return_value=db_review)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"state": "merged"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _orphan_review_sweep()

        assert db_review.verdict == "merged", "Merged MR must get 'merged' verdict"

    @pytest.mark.asyncio
    async def test_deleted_mr_gets_closed_verdict(self):
        ctx, session = _mock_session()
        review = _make_review(id=7, verdict="pending")
        db_review = _make_review(id=7, verdict="pending")

        stale_result = MagicMock()
        stale_result.scalars.return_value.all.return_value = [review]

        session.execute = AsyncMock(return_value=stale_result)
        session.get = AsyncMock(return_value=db_review)

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _orphan_review_sweep()

        assert db_review.verdict == "closed", "Deleted MR must get 'closed' verdict, not 'merged'"


class TestApiUpdateReviewAudit:
    """Bug #1: api_update_review must write audit when verdict changes."""

    @pytest.mark.asyncio
    async def test_verdict_change_writes_audit(self):
        review = MrReview()
        review.id = 1
        review.verdict = "pending"
        review.reviewed_at = None
        review.merged_at = None

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=review)
        mock_session.commit = AsyncMock()

        mock_request = AsyncMock()
        mock_request.json = AsyncMock(return_value={"verdict": "approved"})

        with patch("mcp_hub.main.write_audit_entry", new_callable=AsyncMock) as mock_audit:
            from mcp_hub.main import api_update_review

            result = await api_update_review(1, mock_request, mock_session)

        assert result == {"id": 1, "updated": ["verdict=approved", "reviewed_at auto-set"]}
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args.args[1] == "mr_review"
        assert call_args.args[3] == "pending"
        assert call_args.args[4] == "approved"

    @pytest.mark.asyncio
    async def test_non_verdict_update_skips_audit(self):
        review = MrReview()
        review.id = 2
        review.verdict = "pending"
        review.reviewed_at = None
        review.merged_at = None

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=review)
        mock_session.commit = AsyncMock()

        mock_request = AsyncMock()
        mock_request.json = AsyncMock(return_value={"reason": "looks good"})

        with patch("mcp_hub.main.write_audit_entry", new_callable=AsyncMock) as mock_audit:
            from mcp_hub.main import api_update_review

            result = await api_update_review(2, mock_request, mock_session)

        assert result == {"id": 2, "updated": ["reason updated"]}
        mock_audit.assert_not_called()


class TestShaDriftReset:
    """_sha_drift_reset must reset non-pending verdicts when commit SHA changes."""

    def _make_candidate(self, **overrides) -> MagicMock:
        defaults = {
            "id": 1,
            "project_id": 5,
            "mr_iid": 124,
            "verdict": "approved",
            "commit_sha": "65db467abc123",
            "reason": "Looks good",
            "details": "All checks pass",
            "reviewer_model": "sonnet",
            "reviewed_at": datetime.now(UTC) - timedelta(hours=1),
        }
        defaults.update(overrides)
        obj = MagicMock()
        for k, v in defaults.items():
            setattr(obj, k, v)
        return obj

    def _mock_session(self) -> tuple:
        session = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx, session

    @pytest.mark.asyncio
    async def test_resets_approved_on_sha_change(self):
        """Approved MR with a new live SHA must be reset to pending."""
        ctx, session = self._mock_session()
        candidate = self._make_candidate(verdict="approved", commit_sha="old_sha_111")
        db_review = self._make_candidate(verdict="approved", commit_sha="old_sha_111")

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [candidate]
        session.execute = AsyncMock(return_value=candidates_result)
        session.get = AsyncMock(return_value=db_review)

        live_mr_resp = MagicMock()
        live_mr_resp.status_code = 200
        live_mr_resp.json.return_value = {"state": "opened", "sha": "new_sha_999"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock) as mock_audit,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=live_mr_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _sha_drift_reset()

        assert db_review.verdict == "pending"
        assert db_review.commit_sha == "new_sha_999"
        assert db_review.reason is None
        assert db_review.details is None
        assert db_review.reviewer_model is None
        assert db_review.reviewed_at is None
        # updated_at must be backdated so the dispatcher's pending_age guard
        # (< 300s) doesn't delay re-review — the reset is immediate.
        from datetime import UTC, datetime, timedelta

        assert db_review.updated_at < datetime.now(UTC) - timedelta(seconds=300)
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args.args[1] == "mr_review"
        assert call_args.args[3] == "approved"
        assert call_args.args[4] == "pending"

    @pytest.mark.asyncio
    async def test_skips_when_sha_unchanged(self):
        """MR with same live SHA must not be reset."""
        ctx, session = self._mock_session()
        same_sha = "abc123def456"
        candidate = self._make_candidate(verdict="approved", commit_sha=same_sha)

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [candidate]
        session.execute = AsyncMock(return_value=candidates_result)

        live_mr_resp = MagicMock()
        live_mr_resp.status_code = 200
        live_mr_resp.json.return_value = {"state": "opened", "sha": same_sha}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock) as mock_audit,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=live_mr_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _sha_drift_reset()

        session.get.assert_not_called()
        mock_audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_merged_mr_state(self):
        """MR in merged state on GitLab must not be reset (orphan sweep handles it)."""
        ctx, session = self._mock_session()
        candidate = self._make_candidate(verdict="approved", commit_sha="old_sha")

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [candidate]
        session.execute = AsyncMock(return_value=candidates_result)

        live_mr_resp = MagicMock()
        live_mr_resp.status_code = 200
        live_mr_resp.json.return_value = {"state": "merged", "sha": "new_sha_999"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock) as mock_audit,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=live_mr_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _sha_drift_reset()

        session.get.assert_not_called()
        mock_audit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_without_gitlab_token(self):
        """Task must return early when no GitLab token is configured."""
        ctx, session = self._mock_session()

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="", gitlab_url="https://gitlab.test"),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            await _sha_drift_reset()

        session.execute.assert_not_called()
        mock_client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_resets_needs_human_with_null_commit_sha(self):
        """needs_human review with NULL commit_sha must be reset when MR is still open.

        Regression: review 91 (PID22 !7) had verdict=needs_human and commit_sha=None.
        The old query excluded NULL commit_sha rows, so the review was never reset.
        """
        ctx, session = self._mock_session()
        candidate = self._make_candidate(verdict="needs_human", commit_sha=None)
        db_review = self._make_candidate(verdict="needs_human", commit_sha=None)

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [candidate]
        session.execute = AsyncMock(return_value=candidates_result)
        session.get = AsyncMock(return_value=db_review)

        live_mr_resp = MagicMock()
        live_mr_resp.status_code = 200
        live_mr_resp.json.return_value = {"state": "opened", "sha": "current_sha_abc"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock) as mock_audit,
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=live_mr_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _sha_drift_reset()

        assert db_review.verdict == "pending"
        assert db_review.commit_sha == "current_sha_abc"
        assert db_review.reason is None
        assert db_review.details is None
        assert db_review.reviewer_model is None
        assert db_review.reviewed_at is None
        assert db_review.updated_at < datetime.now(UTC) - timedelta(seconds=300)
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args.args[3] == "needs_human"
        assert call_args.args[4] == "pending"

    @pytest.mark.asyncio
    async def test_resets_rejected_on_sha_change(self):
        """Rejected MR with new SHA must also be reset to pending."""
        ctx, session = self._mock_session()
        candidate = self._make_candidate(verdict="rejected", commit_sha="old_rejected_sha")
        db_review = self._make_candidate(verdict="rejected", commit_sha="old_rejected_sha")

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [candidate]
        session.execute = AsyncMock(return_value=candidates_result)
        session.get = AsyncMock(return_value=db_review)

        live_mr_resp = MagicMock()
        live_mr_resp.status_code = 200
        live_mr_resp.json.return_value = {"state": "opened", "sha": "new_rebased_sha"}

        with (
            patch("mcp_hub.tasks.async_session", return_value=ctx),
            patch("mcp_hub.tasks.settings", gitlab_token="test", gitlab_url="https://gitlab.test"),
            patch("mcp_hub.tasks.write_audit_entry", new_callable=AsyncMock),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=live_mr_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            await _sha_drift_reset()

        assert db_review.verdict == "pending"
        assert db_review.commit_sha == "new_rebased_sha"
        from datetime import UTC, datetime, timedelta

        assert db_review.updated_at < datetime.now(UTC) - timedelta(seconds=300)
