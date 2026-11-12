from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import patch

import pytest
from langgraph.types import Command
from app.ai.review_graph import review_graph
from app.ai.review import wait_for_review


@pytest.fixture
def review_run():
    state = {"proposal": {
        "order_id": "BF2026001", "issue_type": "shipping_delay",
        "description": "建议核查发货延迟", "policy_sources": [],
        "checked_at": "2026-11-07T08:00:00+00:00", "approval_status": "pending",
    }, "reviewer_id": None, "reviewed_at": None}
    return state, {"configurable": {"thread_id": str(uuid4())}}


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_already_reviewed_proposal_is_rejected_before_interrupt(review_run, status):
    state, config = review_run
    state["proposal"]["approval_status"] = status
    original = deepcopy(state)
    with patch("app.ai.review.interrupt") as pause, patch("app.ai.review.datetime") as clock:
        with pytest.raises(ValueError, match="无法重复审核"):
            wait_for_review(state)
    pause.assert_not_called()
    clock.now.assert_not_called()
    assert state == original


@pytest.mark.parametrize("status", ["approved", "rejected"])
def test_graph_rejects_completed_proposal(review_run, status):
    state, config = review_run
    state["proposal"]["approval_status"] = status
    with pytest.raises(ValueError, match="无法重复审核"):
        review_graph.invoke(state, config=config)


def test_first_invocation_pauses_without_review_metadata(review_run):
    state, config = review_run
    original = deepcopy(state)
    with patch("app.ai.review.datetime") as clock:
        result = review_graph.invoke(state, config=config)
    clock.now.assert_not_called()
    assert result["__interrupt__"][0].value["proposal"] == state["proposal"]
    assert result["proposal"]["approval_status"] == "pending"
    assert result["reviewer_id"] is None
    assert result["reviewed_at"] is None
    assert review_graph.get_state(config).next == ("review",)
    assert state == original


@pytest.mark.parametrize("action", ["approved", "rejected"])
def test_resume_records_decision_and_server_time(review_run, action):
    state, config = review_run
    original = deepcopy(state)
    review_graph.invoke(state, config=config)
    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    with patch("app.ai.review.datetime") as clock:
        clock.now.return_value = now
        result = review_graph.invoke(Command(resume={
            "decision": action, "reviewer_id": " reviewer-demo-001 ",
            "reviewed_at": "untrusted-client-time",
        }), config=config)
    clock.now.assert_called_once_with(timezone.utc)
    assert result["proposal"]["approval_status"] == action
    assert result["reviewer_id"] == "reviewer-demo-001"
    assert result["reviewed_at"] == now.isoformat()
    assert not result.get("__interrupt__")
    assert review_graph.get_state(config).next == ()
    assert "ticket_id" not in result["proposal"]
    assert state == original


@pytest.mark.parametrize("payload", [
    "approved", {}, {"decision": "pending", "reviewer_id": "demo"},
    {"decision": "approved"}, {"decision": "approved", "reviewer_id": "  "},
    {"decision": "rejected", "reviewer_id": 123},
])
def test_invalid_resume_does_not_commit_review(review_run, payload):
    state, config = review_run
    paused = review_graph.invoke(state, config=config)
    interrupt_id = paused["__interrupt__"][0].id
    with patch("app.ai.review.datetime") as clock:
        with pytest.raises(ValueError):
            # Explicit ID mapping delivers even {} as the actual node input.
            review_graph.invoke(Command(resume={interrupt_id: payload}), config=config)
    clock.now.assert_not_called()
    saved = review_graph.get_state(config).values
    assert saved["proposal"]["approval_status"] == "pending"
    assert saved["reviewer_id"] is None
    assert saved["reviewed_at"] is None
