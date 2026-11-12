from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.models import AgentTask, TaskEvent
from app.repositories.tasks import create_task

EMPLOYEE = {"X-Demo-User": "employee-demo-001"}
MANAGER = {"X-Demo-User": "reviewer-demo-001"}


def create(client):
    response = client.post("/api/v1/agent/tasks", headers=EMPLOYEE,
                           json={"user_input": "private input secret-token"})
    assert response.status_code == 201
    return response.json()["task_id"]


def events(client, task_id, **params):
    response = client.get(f"/api/v1/agent/tasks/{task_id}/events", headers=EMPLOYEE, params=params)
    assert response.status_code == 200
    assert "secret-token" not in response.text
    return response.json()


def test_query_lifecycle_order_pagination_and_no_repeat(client):
    task_id = create(client)
    graph = Mock()
    graph.invoke.return_value = {"answer": "private model answer", "error": None, "approval_id": None}
    with patch("app.services.tasks.get_task_graph", return_value=graph):
        for _ in range(2):
            assert client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE).status_code == 200
    graph.invoke.assert_called_once()
    rows = events(client, task_id)
    assert [row["event_type"] for row in rows] == ["task_created", "task_started", "task_completed"]
    assert [row["status"] for row in rows] == ["created", "running", "completed"]
    assert all(row["created_at"].endswith("+08:00") for row in rows)
    assert "private model answer" not in str(rows)
    assert events(client, task_id, limit=1) == rows[:1]
    assert events(client, task_id, after_id=rows[0]["event_id"]) == rows[1:]
    assert events(client, task_id, after_id=rows[-1]["event_id"]) == []


def test_failure_event_does_not_include_exception(client):
    task_id = create(client)
    with patch("app.services.tasks.get_task_graph", side_effect=RuntimeError("secret-token")):
        assert client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE).json()["status"] == "failed"
    assert events(client, task_id)[-1]["event_type"] == "task_failed"


@pytest.mark.parametrize("headers,status", [({}, 401), (MANAGER, 404)])
def test_event_ownership_is_checked_before_reading(client, headers, status):
    task_id = create(client)
    with patch("app.api.tasks.list_task_events") as read:
        assert client.get(f"/api/v1/agent/tasks/{task_id}/events", headers=headers).status_code == status
        read.assert_not_called()
    assert client.get("/api/v1/agent/tasks/missing/events", headers=EMPLOYEE).status_code == 404


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"after_id": -1}])
def test_pagination_validation(client, params):
    assert client.get("/api/v1/agent/tasks/missing/events", headers=EMPLOYEE, params=params).status_code == 422


def test_task_and_created_event_roll_back_together(db_engine):
    with Session(db_engine) as session:
        with pytest.raises(RuntimeError), session.begin():
            create_task(session, "employee-demo-001", "private input")
            raise RuntimeError("force rollback")
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0
        assert session.scalar(select(func.count()).select_from(TaskEvent)) == 0


def test_missing_event_table_or_write_failure_does_not_advance_task(client, db_engine):
    task_id = create(client)
    failure = OperationalError("private SQL", {}, RuntimeError("secret-token"))
    with patch("app.services.tasks.append_task_event", side_effect=failure), \
         patch("app.services.tasks.get_task_graph") as graph:
        response = client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE)
    assert response.status_code == 503 and "secret-token" not in response.text
    graph.assert_not_called()
    with Session(db_engine) as session:
        assert session.get(AgentTask, task_id).status == "created"
    assert len(events(client, task_id)) == 1


@pytest.mark.parametrize("decision", ["pending", "approved", "rejected"])
def test_refresh_records_observed_decision_once(client, db_engine, decision):
    task_id = create(client)
    with Session(db_engine) as session, session.begin():
        task = session.get(AgentTask, task_id)
        task.status, task.approval_id = "waiting_approval", task_id
    saved = {"proposal": {
        "order_id": "BF2026001", "issue_type": "shipping_delay", "description": "private description",
        "policy_sources": [], "checked_at": "2026-11-09T00:00:00Z", "approval_status": decision,
    }, "reviewer_id": None if decision == "pending" else "reviewer-demo-001",
       "reviewed_at": None if decision == "pending" else "2026-11-09T01:00:00Z"}

    @contextmanager
    def factory():
        graph = Mock()
        graph.get_state.return_value = SimpleNamespace(values=saved)
        yield graph

    with patch("app.services.review_runtime.open_review_graph", factory):
        for _ in range(2):
            response = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
            assert response.status_code == 200
    rows = events(client, task_id)
    assert [row["event_type"] for row in rows] == ["task_created", f"review_{decision}"]
    assert "private description" not in str(rows)


def test_event_query_failure_hides_database_details(client):
    task_id = create(client)
    with patch("app.api.tasks.list_task_events", side_effect=OperationalError("secret-token", {}, Exception())):
        response = client.get(f"/api/v1/agent/tasks/{task_id}/events", headers=EMPLOYEE)
    assert response.status_code == 503 and "secret-token" not in response.text


def test_old_task_has_no_fabricated_history(client, db_engine):
    task_id = create(client)
    # Model a task created before event collection was introduced.
    with Session(db_engine) as session, session.begin():
        from sqlalchemy import delete
        session.execute(delete(TaskEvent).where(TaskEvent.task_id == task_id))
    assert events(client, task_id) == []
