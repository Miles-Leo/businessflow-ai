from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import DemoUser, require_reviewer


# Isolated probe: no actual approval endpoint or business writes.
app = FastAPI()


@app.get("/reviewer")
def probe(user: Annotated[DemoUser, Depends(require_reviewer)]):
    return {"reviewer_id": user.user_id}


client = TestClient(app)


@pytest.mark.parametrize("headers", [{}, {"X-Demo-User": "unknown"}, {"X-Demo-User": ""}])
def test_missing_or_unknown_identity_is_rejected(headers):
    assert client.get("/reviewer", headers=headers).status_code == 401


def test_employee_cannot_select_manager_role():
    response = client.get("/reviewer", headers={
        "X-Demo-User": "employee-demo-001", "X-Role": "manager",
        "X-Reviewer-Id": "reviewer-demo-001",
    })
    assert response.status_code == 403


def test_manager_identity_comes_from_server_mapping():
    response = client.get("/reviewer", headers={"X-Demo-User": "reviewer-demo-001"})
    assert response.status_code == 200
    assert response.json() == {"reviewer_id": "reviewer-demo-001"}
