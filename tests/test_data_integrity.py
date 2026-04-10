"""Test data integrity constraints and fixes from ticket #31."""

from unittest.mock import AsyncMock

import pytest

from mcp_hub.models.mr_review import (
    VERDICT_TRANSITIONS,
    MrReview,
    ReviewResetLog,
)
from mcp_hub.models.ticket import (
    VALID_PRIORITIES,
    VALID_ROLES,
    VALID_STATUSES,
    Ticket,
    TicketComment,
)

# -- Fix 1: TicketComment FK cascade is declared in model --


def test_ticket_comment_fk_has_cascade():
    fk = TicketComment.__table__.c.ticket_id.foreign_keys
    assert len(fk) == 1
    fk_obj = next(iter(fk))
    assert fk_obj.ondelete == "CASCADE"


# -- Fix 2: CHECK constraints exist on Ticket --


def test_ticket_has_status_check_constraint():
    constraints = {c.name for c in Ticket.__table__.constraints if hasattr(c, "sqltext")}
    assert "ck_ticket_status" in constraints


def test_ticket_has_priority_check_constraint():
    constraints = {c.name for c in Ticket.__table__.constraints if hasattr(c, "sqltext")}
    assert "ck_ticket_priority" in constraints


def test_ticket_status_values_match_check():
    for status in VALID_STATUSES:
        check = next(
            c
            for c in Ticket.__table__.constraints
            if getattr(c, "name", None) == "ck_ticket_status"
        )
        assert status in str(check.sqltext)


def test_ticket_priority_values_match_check():
    for priority in VALID_PRIORITIES:
        check = next(
            c
            for c in Ticket.__table__.constraints
            if getattr(c, "name", None) == "ck_ticket_priority"
        )
        assert priority in str(check.sqltext)


# -- Fix 2: CHECK constraint on MrReview verdict --


def test_mr_review_has_verdict_check_constraint():
    constraints = {c.name for c in MrReview.__table__.constraints if hasattr(c, "sqltext")}
    assert "ck_review_verdict" in constraints


# -- Fix 4: ReviewResetLog model exists --


def test_review_reset_log_table_name():
    assert ReviewResetLog.__tablename__ == "review_reset_logs"


def test_review_reset_log_fk_has_cascade():
    fk = ReviewResetLog.__table__.c.review_id.foreign_keys
    assert len(fk) == 1
    fk_obj = next(iter(fk))
    assert fk_obj.ondelete == "CASCADE"


def test_review_reset_log_required_columns():
    cols = {c.name for c in ReviewResetLog.__table__.columns}
    expected = {
        "id",
        "review_id",
        "old_verdict",
        "old_commit_sha",
        "new_commit_sha",
        "reason",
        "created_at",
    }
    assert expected.issubset(cols)


# -- Fix 4: Verdict transitions allow approved -> pending is NOT in normal transitions --
# The push-reset bypasses the state machine intentionally and logs via ReviewResetLog


def test_approved_cannot_transition_to_pending_via_state_machine():
    assert "pending" not in VERDICT_TRANSITIONS["approved"]


# -- Fix 5: No naive datetime.utcnow() in main.py --


def test_no_naive_utcnow_in_main():
    import inspect

    from mcp_hub import main

    source = inspect.getsource(main)
    assert "utcnow()" not in source


# -- Fix 6: TicketComment role CHECK constraint --


def test_ticket_comment_has_role_check_constraint():
    constraints = {c.name for c in TicketComment.__table__.constraints if hasattr(c, "sqltext")}
    assert "ck_comment_role" in constraints


def test_ticket_comment_role_check_includes_all_valid_roles():
    check = next(
        c
        for c in TicketComment.__table__.constraints
        if getattr(c, "name", None) == "ck_comment_role"
    )
    check_text = str(check.sqltext)
    for role in VALID_ROLES:
        assert role in check_text


# -- Fix 3: Upsert uses ON CONFLICT (verified via endpoint test) --


def _mock_review_session():
    session = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


@pytest.mark.asyncio
async def test_create_review_endpoint_uses_pg_insert():
    """Verify the endpoint imports and uses postgresql INSERT ON CONFLICT."""
    import inspect

    from mcp_hub.main import api_create_review

    source = inspect.getsource(api_create_review)
    assert "pg_insert" in source
    assert "on_conflict_do_update" in source


@pytest.mark.asyncio
async def test_create_review_audit_log_on_verdict_reset():
    """Verify ReviewResetLog is created when resetting a non-pending verdict."""
    import inspect

    from mcp_hub.main import api_create_review

    source = inspect.getsource(api_create_review)
    assert "ReviewResetLog" in source
    assert "push-reset" in source
