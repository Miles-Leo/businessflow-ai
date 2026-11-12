from unittest.mock import patch
import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.db.models import AgentTask

EMPLOYEE = {"X-Demo-User": "employee-demo-001"}
MANAGER = {"X-Demo-User": "reviewer-demo-001"}


def test_create_commits_and_get_roundtrips_without_execution(client, db_engine):
    with patch("app.api.agent.get_agent_graph") as graph:
        response = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json={"user_input": "  查询订单 BF2026001  "})
        graph.assert_not_called()
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "created"
    assert data["user_id"] == "employee-demo-001"
    assert data["user_input"] == "查询订单 BF2026001"
    assert data["approval_id"] is data["ticket_id"] is data["error"] is None
    assert data["created_at"] == data["updated_at"]
    with Session(db_engine) as session:
        assert session.get(AgentTask, data["task_id"]).status == "created"
    read = client.get(response.headers["location"], headers=EMPLOYEE)
    assert read.status_code == 200 and read.json() == data


def test_task_ownership_applies_to_manager_too(client):
    a = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json={"user_input": "员工任务"}).json()
    b = client.post("/api/v1/agent/tasks", headers=MANAGER, json={"user_input": "负责人任务"}).json()
    assert a["task_id"] != b["task_id"]
    assert client.get(f"/api/v1/agent/tasks/{a['task_id']}", headers=MANAGER).status_code == 404
    assert client.get(f"/api/v1/agent/tasks/{b['task_id']}", headers=EMPLOYEE).status_code == 404
    assert client.get(f"/api/v1/agent/tasks/{b['task_id']}", headers=MANAGER).status_code == 200


@pytest.mark.parametrize("payload", [
    {}, {"user_input": ""}, {"user_input": " \t "}, {"user_input": "a" * 2001},
    {"user_input": "任务", "user_id": "reviewer-demo-001"},
    {"user_input": "任务", "status": "completed"},
    {"user_input": "任务", "approval_id": "fake"},
])
def test_invalid_task_never_inserts(client, db_engine, payload):
    response = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json=payload)
    assert response.status_code == 422
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0


@pytest.mark.parametrize("headers", [{}, {"X-Demo-User": "unknown"}])
def test_tasks_require_known_identity(client, headers):
    assert client.post("/api/v1/agent/tasks", headers=headers, json={"user_input": "任务"}).status_code == 401
    assert client.get("/api/v1/agent/tasks/unknown", headers=headers).status_code == 401


def test_unknown_task_is_not_found(client):
    assert client.get("/api/v1/agent/tasks/missing", headers=EMPLOYEE).status_code == 404


def test_insert_failure_rolls_back_and_hides_error(client, db_engine):
    from app.repositories.tasks import create_task
    def fail_after_flush(session, user_id, user_input):
        create_task(session, user_id, user_input)
        raise OperationalError("secret SQL", {}, RuntimeError("secret"))
    with patch("app.api.tasks.create_task", side_effect=fail_after_flush):
        response = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json={"user_input": "任务"})
    assert response.status_code == 503
    assert "secret" not in response.text
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(AgentTask)) == 0


def test_get_failure_hides_error(client):
    with patch("app.api.tasks.get_owned_task", side_effect=OperationalError("secret", {}, RuntimeError("secret"))):
        response = client.get("/api/v1/agent/tasks/unknown", headers=EMPLOYEE)
    assert response.status_code == 503 and "secret" not in response.text
