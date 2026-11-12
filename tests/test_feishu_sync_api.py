from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.schemas.feishu_sync import FeishuSyncResponse
from app.services.feishu_sync import SyncNotFound, SyncConflict

client = TestClient(app)
headers = {"X-Demo-User": "reviewer-demo-001"}


def result(status="success"):
    return FeishuSyncResponse(ticket_id="TK", request_id="uuid", status=status, record_id="rec" if status == "success" else None,
                              attempts=1, requested_by="reviewer-demo-001", error=None, updated_at=datetime.now(timezone.utc))


def test_sync_endpoint_uses_server_identity():
    with patch("app.api.feishu_sync.sync_ticket", return_value=result()) as sync:
        response = client.post("/api/v1/tickets/TK/feishu-sync", headers=headers)
    assert response.status_code == 200 and response.json()["record_id"] == "rec"
    assert sync.call_args.args[1:] == ("TK", "reviewer-demo-001")


@pytest.mark.parametrize("method,path,target", [("post", "/feishu-sync", "sync_ticket"), ("get", "/feishu-sync", "get_sync"), ("post", "/feishu-sync/reconcile", "reconcile_sync")])
def test_employee_cannot_sync_read_or_reconcile(method, path, target):
    with patch("app.api.feishu_sync." + target) as service:
        response = getattr(client, method)("/api/v1/tickets/TK" + path, headers={"X-Demo-User": "employee-demo-001"})
    assert response.status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("failure,status", [(SyncNotFound("missing"),404), (SyncConflict("conflict"),409), (RuntimeError("secret"),503)])
def test_sync_errors_are_safe(failure,status):
    with patch("app.api.feishu_sync.sync_ticket", side_effect=failure):
        response = client.post("/api/v1/tickets/TK/feishu-sync",headers=headers)
    assert response.status_code == status
    assert "secret" not in response.text


@pytest.mark.parametrize("status", ["failed", "unknown"])
def test_unsuccessful_sync_not_http_success(status):
    with patch("app.api.feishu_sync.sync_ticket", return_value=result(status)):
        assert client.post("/api/v1/tickets/TK/feishu-sync",headers=headers).status_code == 503


def test_status_and_reconcile_routes():
    with patch("app.api.feishu_sync.get_sync", return_value=result()), patch("app.api.feishu_sync.reconcile_sync", return_value=result()):
        assert client.get("/api/v1/tickets/TK/feishu-sync",headers=headers).status_code == 200
        assert client.post("/api/v1/tickets/TK/feishu-sync/reconcile",headers=headers).json()["record_id"] == "rec"
