from contextlib import contextmanager
from unittest.mock import patch

import pytest

from app.services.approval import start_review, submit_review
from app.services.review_runtime import open_review_graph, review_lock

MANAGER = {"X-Demo-User": "reviewer-demo-001"}
EMPLOYEE = {"X-Demo-User": "employee-demo-001"}


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / "inbox.db"
    path.touch()

    @contextmanager
    def factory():
        with open_review_graph(path) as graph:
            yield graph

    with factory() as graph:
        for index, approval_id in enumerate(["pending-a", "approved-b", "rejected-c"], 1):
            proposal = {"order_id": f"BF202600{index}", "issue_type": "shipping_delay",
                        "description": "审核事实摘要" * 40, "policy_sources": [],
                        "checked_at": "2026-10-01T08:00:00Z", "approval_status": "pending"}
            start_review(graph, proposal, approval_id=approval_id)
        submit_review(graph, "approved-b", "approved", "reviewer-demo-001")
        submit_review(graph, "rejected-c", "rejected", "reviewer-demo-001")
    with patch("app.api.approvals.open_review_graph", factory):
        yield factory


def test_defaults_to_actionable_pending_reviews_and_uses_submission_time(client, inbox):
    response = client.get("/api/v1/approvals", headers=MANAGER)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1 and data["unavailable_count"] == 0
    assert data["items"][0]["approval_id"] == "pending-a"
    assert data["items"][0]["order_id"] == "BF2026001"
    assert data["items"][0]["submitted_at"] != "2026-10-01T08:00:00Z"
    assert len(data["items"][0]["description"]) == 180
    assert "user_input" not in data["items"][0]


def test_latest_state_deduplication_filter_search_and_pagination(client, inbox):
    data = client.get("/api/v1/approvals?status=all", headers=MANAGER).json()
    assert data["total"] == 3
    assert [item["approval_id"] for item in data["items"]] == ["pending-a", "approved-b", "rejected-c"]
    assert [item["approval_status"] for item in data["items"]] == ["pending", "approved", "rejected"]
    page = client.get("/api/v1/approvals?status=all&offset=1&limit=1", headers=MANAGER).json()
    assert page["items"][0]["approval_id"] == "approved-b"
    assert client.get("/api/v1/approvals?status=approved", headers=MANAGER).json()["total"] == 1
    found = client.get("/api/v1/approvals?status=all&query=BF2026003", headers=MANAGER).json()
    assert found["items"][0]["approval_id"] == "rejected-c"
    assert client.get("/api/v1/approvals?query=missing", headers=MANAGER).json()["items"] == []


def test_decision_removes_pending_item_but_keeps_readable_history(client, inbox):
    response = client.post("/api/v1/approvals/pending-a/decision", headers=MANAGER, json={"decision": "approved"})
    assert response.status_code == 200
    assert client.get("/api/v1/approvals", headers=MANAGER).json()["total"] == 0
    assert client.get("/api/v1/approvals?status=approved", headers=MANAGER).json()["total"] == 2
    assert client.get("/api/v1/approvals/pending-a", headers=MANAGER).status_code == 200


@pytest.mark.parametrize("headers,status", [({}, 401), (EMPLOYEE, 403)])
def test_inbox_is_manager_only(client, headers, status):
    with patch("app.api.approvals.open_review_graph") as factory:
        assert client.get("/api/v1/approvals", headers=headers).status_code == status
        factory.assert_not_called()


@pytest.mark.parametrize("query", ["status=invalid", "offset=-1", "limit=0", "limit=101"])
def test_invalid_list_parameters(client, query):
    assert client.get(f"/api/v1/approvals?{query}", headers=MANAGER).status_code == 422


def test_list_lock_and_errors_are_safe(client, inbox):
    with review_lock:
        assert client.get("/api/v1/approvals", headers=MANAGER).status_code == 409
    with patch("app.api.approvals.open_review_graph", side_effect=RuntimeError("secret")):
        response = client.get("/api/v1/approvals", headers=MANAGER)
    assert response.status_code == 503 and "secret" not in response.text


def test_corrupt_record_is_reported_without_hiding_valid_items(client, inbox):
    with inbox() as graph:
        graph.update_state({"configurable": {"thread_id": "incomplete"}}, {"proposal": {"approval_status": "pending"}})
    result = client.get("/api/v1/approvals", headers=MANAGER).json()
    assert result["total"] == 1 and result["unavailable_count"] == 1
