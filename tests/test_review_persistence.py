from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.ai.review import wait_for_review
from app.ai.state import TicketReviewState


@contextmanager
def open_graph(path):
    # Recreate both connection and graph to model application restart.
    with SqliteSaver.from_conn_string(str(path)) as saver:
        builder = StateGraph(TicketReviewState)
        builder.add_node("review", wait_for_review)
        builder.add_edge(START, "review")
        builder.add_edge("review", END)
        yield builder.compile(checkpointer=saver)


def initial_state(order_id="BF2026001"):
    return {"proposal": {
        "order_id": order_id, "issue_type": "shipping_delay", "description": "演示建议",
        "policy_sources": [{"document_title": "测试政策", "section": "AS-05",
                            "source": "policy.md", "chunk_id": "policy:5"}],
        "checked_at": "2026-11-07T08:00:00+00:00", "approval_status": "pending",
    }, "reviewer_id": None, "reviewed_at": None}


@pytest.mark.parametrize("action", ["approved", "rejected"])
def test_reopen_database_resumes_and_persists_decision(tmp_path, action):
    database = tmp_path / "checkpoints.db"
    config = {"configurable": {"thread_id": "persistent-review"}}
    state = initial_state()
    with open_graph(database) as graph:
        paused = graph.invoke(state, config=config)
        interrupt_id = paused["__interrupt__"][0].id

    now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    with open_graph(database) as graph:
        snapshot = graph.get_state(config)
        assert snapshot.values == state
        assert snapshot.next == ("review",)
        assert snapshot.tasks[0].interrupts[0].id == interrupt_id
        with patch("app.ai.review.datetime") as clock:
            clock.now.return_value = now
            result = graph.invoke(Command(resume={interrupt_id: {
                "decision": action, "reviewer_id": " reviewer-demo ",
                "reviewed_at": "untrusted-time",
            }}), config=config)
        clock.now.assert_called_once_with(timezone.utc)
        assert result["proposal"]["approval_status"] == action

    with open_graph(database) as graph:
        saved = graph.get_state(config)
        assert saved.values == result
        assert saved.next == ()
        assert saved.values["reviewer_id"] == "reviewer-demo"
        assert saved.values["reviewed_at"] == now.isoformat()
        assert "ticket_id" not in saved.values["proposal"]


def test_review_threads_remain_isolated_after_reopening(tmp_path):
    database = tmp_path / "checkpoints.db"
    a = {"configurable": {"thread_id": "A"}}
    b = {"configurable": {"thread_id": "B"}}
    with open_graph(database) as graph:
        graph.invoke(initial_state("BF2026001"), config=a)
        graph.invoke(initial_state("BF2026002"), config=b)
    with open_graph(database) as graph:
        graph.invoke(Command(resume={"decision": "approved", "reviewer_id": "reviewer-A"}), config=a)
    with open_graph(database) as graph:
        pending_b = graph.get_state(b)
        assert pending_b.values["proposal"]["approval_status"] == "pending"
        assert pending_b.values["reviewer_id"] is None
        assert pending_b.next == ("review",)
        graph.invoke(Command(resume={"decision": "rejected", "reviewer_id": "reviewer-B"}), config=b)
    with open_graph(database) as graph:
        saved_a, saved_b = graph.get_state(a), graph.get_state(b)
        assert saved_a.values["proposal"]["approval_status"] == "approved"
        assert saved_a.values["proposal"]["order_id"] == "BF2026001"
        assert saved_a.values["reviewer_id"] == "reviewer-A"
        assert saved_b.values["proposal"]["approval_status"] == "rejected"
        assert saved_b.values["reviewer_id"] == "reviewer-B"
        assert saved_a.next == saved_b.next == ()


def test_unknown_thread_does_not_load_existing_review(tmp_path):
    database = tmp_path / "checkpoints.db"
    with open_graph(database) as graph:
        graph.invoke(initial_state(), config={"configurable": {"thread_id": "existing"}})
    with open_graph(database) as graph:
        snapshot = graph.get_state({"configurable": {"thread_id": "unknown"}})
        assert snapshot.values == {}
        assert snapshot.next == ()
