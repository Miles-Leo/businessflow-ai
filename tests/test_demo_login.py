import pytest

EMPLOYEE = "employee-demo-001"
MANAGER = "reviewer-demo-001"


def test_login_cookie_profile_and_logout(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    response = client.post("/api/v1/auth/login", json={"user_id": EMPLOYEE})
    assert response.status_code == 200
    assert response.json()["role"] == "employee"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/v1/auth/me").json()["user_id"] == EMPLOYEE
    assert client.get("/api/v1/orders/BF2026001").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.get("/api/v1/orders/BF2026001").status_code == 401


def test_employee_session_cannot_be_overridden_by_header(client):
    client.post("/api/v1/auth/login", json={"user_id": EMPLOYEE})
    spoofed = {"X-Demo-User": MANAGER}
    assert client.get("/api/v1/approvals", headers=spoofed).status_code == 403
    assert client.get("/api/v1/auth/me", headers=spoofed).json()["role"] == "employee"


def test_me_requires_actual_session_but_swagger_header_still_works(client):
    assert client.get("/api/v1/auth/me", headers={"X-Demo-User": MANAGER}).status_code == 401
    assert client.get("/api/v1/orders/BF2026001", headers={"X-Demo-User": EMPLOYEE}).status_code == 200


@pytest.mark.parametrize("payload", [{}, {"user_id": "admin"}, {"user_id": EMPLOYEE, "role": "manager"}])
def test_invalid_demo_login(client, payload):
    assert client.post("/api/v1/auth/login", json=payload).status_code == 422
    assert client.get("/api/v1/auth/me").status_code == 401


def test_manager_lands_with_own_profile_and_can_read_inbox(client):
    client.post("/api/v1/auth/login", json={"user_id": MANAGER})
    assert client.get("/api/v1/auth/me").json()["role"] == "manager"
    # Check role without opening the project checkpoint DB.
    from unittest.mock import patch
    with patch("app.api.approvals.open_review_graph", side_effect=RuntimeError("offline")):
        assert client.get("/api/v1/approvals").status_code == 503


def test_my_tasks_come_from_backend_and_never_include_another_owner(client):
    employee_ids = []
    for number in range(3):
        result = client.post("/api/v1/agent/tasks", headers={"X-Demo-User": EMPLOYEE}, json={"user_input": f"employee {number}"})
        employee_ids.append(result.json()["task_id"])
    manager_task = client.post("/api/v1/agent/tasks", headers={"X-Demo-User": MANAGER}, json={"user_input": "private manager input"}).json()
    client.post("/api/v1/auth/login", json={"user_id": EMPLOYEE})
    result = client.get("/api/v1/agent/tasks?limit=2").json()
    assert result["total"] == 3 and len(result["items"]) == 2
    assert [item["task_id"] for item in result["items"]] == employee_ids[::-1][:2]
    page = client.get("/api/v1/agent/tasks?offset=2&limit=2").json()
    assert page["items"][0]["task_id"] == employee_ids[0]
    assert manager_task["task_id"] not in str(result)
    assert client.get(f"/api/v1/agent/tasks/{manager_task['task_id']}").status_code == 404
    assert client.get("/api/v1/agent/tasks?user_id=reviewer-demo-001").json()["total"] == 3
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={"user_id": EMPLOYEE})
    assert client.get("/api/v1/agent/tasks").json()["total"] == 3


@pytest.mark.parametrize("params", ["limit=0", "limit=101", "offset=-1"])
def test_my_tasks_pagination_validation(client, params):
    client.post("/api/v1/auth/login", json={"user_id": EMPLOYEE})
    assert client.get(f"/api/v1/agent/tasks?{params}").status_code == 422
