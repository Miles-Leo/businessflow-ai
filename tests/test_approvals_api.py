from datetime import datetime
from contextlib import contextmanager
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import StateGraph, START, END
from app.main import app
from app.ai.review import wait_for_review
from app.ai.state import TicketReviewState
from app.api.approvals import _review_lock

client = TestClient(app)
HEADERS = {"X-Demo-User": "reviewer-demo-001"}

@pytest.fixture
def review_factory(tmp_path, db_engine, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=db_engine))
    database = tmp_path / "reviews.db"
    @contextmanager
    def factory():
        with SqliteSaver.from_conn_string(str(database)) as saver:
            builder = StateGraph(TicketReviewState)
            builder.add_node("review", wait_for_review)
            builder.add_edge(START, "review")
            builder.add_edge("review", END)
            yield builder.compile(checkpointer=saver)
    with factory() as graph:
        graph.invoke({"proposal": {"order_id": "BF2026001", "issue_type": "shipping_delay", "description": "测试", "policy_sources": [], "checked_at": "2026-11-08T00:00:00Z", "approval_status": "pending"}, "reviewer_id": None, "reviewed_at": None}, config={"configurable": {"thread_id": "demo"}})
    return factory

@pytest.mark.parametrize("action", ["approved", "rejected"])
def test_decision_persists_and_repeat_is_conflict(review_factory, action):
    with patch("app.api.approvals.open_review_graph", review_factory):
        response = client.post("/api/v1/approvals/demo/decision", headers=HEADERS, json={"decision": action})
        repeated = client.post("/api/v1/approvals/demo/decision", headers=HEADERS, json={"decision": action})
    assert response.status_code == 200
    data = response.json()
    assert data["approval_status"] == action
    assert data["reviewer_id"] == "reviewer-demo-001"
    assert data["reviewed_at"]
    assert repeated.status_code == 409
    with review_factory() as graph:
        state = graph.get_state({"configurable": {"thread_id": "demo"}}).values
        assert state["proposal"]["approval_status"] == action
        assert datetime.fromisoformat(state["reviewed_at"]) == datetime.fromisoformat(data["reviewed_at"])
        assert data["reviewed_at"].endswith("+08:00")

@pytest.mark.parametrize("headers,status", [({},401), ({"X-Demo-User":"unknown"},401), ({"X-Demo-User":"employee-demo-001"},403)])
def test_unauthorized_does_not_open_database(headers,status):
    with patch("app.api.approvals.open_review_graph") as factory:
        response = client.post("/api/v1/approvals/demo/decision", headers=headers,json={"decision":"approved"})
    assert response.status_code == status
    factory.assert_not_called()

@pytest.mark.parametrize("payload", [{"decision":"pending"}, {"decision":"approved","reviewer_id":"fake"}, {"decision":"approved","reviewed_at":"fake"}])
def test_invalid_body_skips_database(payload):
    with patch("app.api.approvals.open_review_graph") as factory:
        response = client.post("/api/v1/approvals/demo/decision",headers=HEADERS,json=payload)
    assert response.status_code == 422
    factory.assert_not_called()

def test_missing_task(review_factory):
    with patch("app.api.approvals.open_review_graph",review_factory):
        response = client.post("/api/v1/approvals/unknown/decision",headers=HEADERS,json={"decision":"approved"})
    assert response.status_code == 404

def test_busy_review_is_rejected():
    with _review_lock:
        response = client.post("/api/v1/approvals/demo/decision",headers=HEADERS,json={"decision":"approved"})
    assert response.status_code == 409

def test_internal_error_is_safe_and_lock_released():
    with patch("app.api.approvals.open_review_graph",side_effect=RuntimeError("secret")):
        response = client.post("/api/v1/approvals/demo/decision",headers=HEADERS,json={"decision":"approved"})
    assert response.status_code == 503
    assert "secret" not in response.text
    assert not _review_lock.locked()


def test_detail_reads_pending_task_without_modifying_checkpoint(review_factory):
    config = {"configurable": {"thread_id": "demo"}}
    with review_factory() as graph:
        before = graph.get_state(config)
    with patch("app.api.approvals.open_review_graph", review_factory):
        response = client.get("/api/v1/approvals/demo", headers=HEADERS)
        again = client.get("/api/v1/approvals/demo", headers=HEADERS)
    assert response.status_code == again.status_code == 200
    assert response.json() == again.json()
    body = response.json()
    assert body["proposal"]["approval_status"] == "pending"
    assert body["proposal"]["order_id"] == "BF2026001"
    assert body["reviewer_id"] is None
    assert body["reviewed_at"] is None
    with review_factory() as graph:
        after = graph.get_state(config)
    assert before.config == after.config
    assert before.values == after.values
    assert after.next == ("review",)


@pytest.mark.parametrize("action", ["approved", "rejected"])
def test_detail_can_read_completed_task(review_factory, action):
    with patch("app.api.approvals.open_review_graph", review_factory):
        decision = client.post("/api/v1/approvals/demo/decision", headers=HEADERS, json={"decision": action})
        response = client.get("/api/v1/approvals/demo", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["proposal"]["approval_status"] == action
    assert response.json()["reviewed_at"] == decision.json()["reviewed_at"]
    assert response.json()["reviewer_id"] == "reviewer-demo-001"


@pytest.mark.parametrize("headers,status", [({},401), ({"X-Demo-User":"unknown"},401), ({"X-Demo-User":"employee-demo-001"},403)])
def test_detail_requires_reviewer_before_opening_database(headers, status):
    with patch("app.api.approvals.open_review_graph") as factory:
        response = client.get("/api/v1/approvals/demo", headers=headers)
    assert response.status_code == status
    factory.assert_not_called()


def test_detail_unknown_task(review_factory):
    with patch("app.api.approvals.open_review_graph", review_factory):
        response = client.get("/api/v1/approvals/unknown", headers=HEADERS)
    assert response.status_code == 404


def test_detail_error_hides_internal_information():
    with patch("app.api.approvals.open_review_graph", side_effect=RuntimeError("secret")):
        response = client.get("/api/v1/approvals/demo", headers=HEADERS)
    assert response.status_code == 503
    assert "secret" not in response.text


def test_create_review_then_read_and_decide(review_factory):
    with patch("app.api.approvals.open_review_graph", review_factory):
        assert client.post("/api/v1/approvals/demo/decision", headers=HEADERS, json={"decision":"rejected"}).status_code == 200
    proposal = {"order_id": "BF2026001", "issue_type": "shipping_delay", "description": "真实工具建议的模拟结果",
                "policy_sources": [{"document_title": "政策", "section": "AS-05", "source": "policy.md", "chunk_id": "policy:5"}],
                "checked_at": "2026-11-08T00:00:00Z", "approval_status": "pending"}
    with patch("app.api.approvals.open_review_graph", review_factory), patch(
        "app.api.approvals.prepare_proposal", return_value=proposal
    ) as prepare:
        created = client.post("/api/v1/approvals", headers={"X-Demo-User": "employee-demo-001"}, json={"order_id": "BF2026001"})
        assert created.status_code == 201
        approval_id = created.json()["approval_id"]
        detail = client.get(f"/api/v1/approvals/{approval_id}", headers=HEADERS)
        assert detail.status_code == 200
        assert detail.json()["proposal"]["approval_status"] == "pending"
        assert detail.json()["proposal"]["policy_sources"] == proposal["policy_sources"]
        assert detail.json()["reviewer_id"] is None
        decided = client.post(f"/api/v1/approvals/{approval_id}/decision", headers=HEADERS, json={"decision": "rejected"})
        assert decided.status_code == 200
        assert decided.json()["approval_status"] == "rejected"
    prepare.assert_called_once_with("BF2026001")


@pytest.mark.parametrize("payload", [{}, {"order_id": "abc"}, {"order_id": "BF2026001", "approval_status": "approved"}])
def test_invalid_create_never_prepares_or_starts(payload):
    with patch("app.api.approvals.prepare_proposal") as prepare, patch("app.api.approvals.open_review_graph") as factory:
        response = client.post("/api/v1/approvals", headers=HEADERS, json=payload)
    assert response.status_code == 422
    prepare.assert_not_called()
    factory.assert_not_called()


def test_create_requires_demo_identity():
    with patch("app.api.approvals.prepare_proposal") as prepare:
        response = client.post("/api/v1/approvals", json={"order_id": "BF2026001"})
    assert response.status_code == 401
    prepare.assert_not_called()


@pytest.mark.parametrize("failure,status", [(ValueError("secret"), 409), (RuntimeError("secret"), 503)])
def test_create_failure_does_not_start_review(review_factory, failure, status):
    with patch("app.api.approvals.open_review_graph", review_factory), patch(
        "app.api.approvals.prepare_proposal", side_effect=failure
    ), patch("app.api.approvals.start_review") as start:
        response = client.post("/api/v1/approvals", headers=HEADERS, json={"order_id": "BF2026001"})
    assert response.status_code == status
    assert "secret" not in response.text
    start.assert_not_called()
    assert not _review_lock.locked()
