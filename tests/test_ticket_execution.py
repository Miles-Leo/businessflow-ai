from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from unittest.mock import patch
from types import SimpleNamespace

import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.db.models import Ticket, TicketExecution, Order
from app.services.tickets import execute_ticket, TicketExecutionConflict
from app.main import app
from app.db.session import get_db


@pytest.fixture
def approved():
    return {"proposal": {"order_id": "BF2026001", "issue_type": "shipping_delay", "description": "建议核查延迟",
        "policy_sources": [{"document_title": "政策", "section": c + "：条款", "source": "policy.md", "chunk_id": c} for c in ("AS-04", "AS-05")],
        "checked_at": "2026-11-07T08:00:00Z", "approval_status": "approved"},
        "reviewer_id": "reviewer-demo-001", "reviewed_at": "2026-11-08T00:00:00Z"}


def test_success_repeat_and_reopen_return_same_ticket(db_engine, approved):
    with Session(db_engine) as s:
        first = execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        second = execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
        assert s.scalar(select(func.count()).select_from(Ticket)) == 1
        record = s.get(TicketExecution, "approval-1")
        assert record.status == "success"
        assert record.attempts == 1
    assert first.ticket.ticket_id == second.ticket.ticket_id
    assert first.reused is False and second.reused is True


def test_different_approvals_cannot_create_two_active_tickets(db_engine, approved):
    def attempt(approval_id):
        with Session(db_engine) as session:
            try:
                return execute_ticket(session, approval_id, approved, 'reviewer-demo-001').ticket.ticket_id
            except TicketExecutionConflict:
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ['approval-one', 'approval-two']))
    assert sum(value is not None for value in results) == 1
    with Session(db_engine) as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 1


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_unapproved_never_creates_ticket(db_engine, approved, status):
    approved["proposal"]["approval_status"] = status
    with Session(db_engine) as s:
        with pytest.raises(TicketExecutionConflict):
            execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
        assert s.scalar(select(func.count()).select_from(Ticket)) == 0


@pytest.mark.parametrize("reviewer,time", [(None, None), ("reviewer", None)])
def test_incomplete_audit_is_rejected(db_engine, approved, reviewer, time):
    approved.update(reviewer_id=reviewer, reviewed_at=time)
    with Session(db_engine) as s:
        with pytest.raises(TicketExecutionConflict):
            execute_ticket(s, "approval-1", approved, "reviewer-demo-001")


def test_changed_order_records_failure_without_ticket(db_engine, approved):
    with Session(db_engine) as s, s.begin():
        o = s.get(Order, "BF2026001")
        o.status = "shipped"
        o.shipped_at = datetime(2026, 10, 3, tzinfo=timezone.utc)
    with Session(db_engine) as s:
        with pytest.raises(TicketExecutionConflict):
            execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        assert s.scalar(select(func.count()).select_from(Ticket)) == 0
        assert s.get(TicketExecution, "approval-1").status == "failed"


def test_missing_policy_is_failure(db_engine, approved):
    approved["proposal"]["policy_sources"] = []
    with Session(db_engine) as s:
        with pytest.raises(TicketExecutionConflict):
            execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        assert s.get(TicketExecution, "approval-1").ticket_id is None


def test_failure_can_retry_without_duplicate_ticket(db_engine, approved):
    with Session(db_engine) as s, s.begin():
        s.get(Order, "BF2026001").status = "shipped"
    with Session(db_engine) as s:
        with pytest.raises(TicketExecutionConflict):
            execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s, s.begin():
        s.get(Order, "BF2026001").status = "pending"
    with Session(db_engine) as s:
        result = execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        record = s.get(TicketExecution, "approval-1")
        assert record.status == "success"
        assert record.attempts == 2
        assert record.error is None
        assert record.ticket_id == result.ticket.ticket_id
        assert s.scalar(select(func.count()).select_from(Ticket)) == 1


def test_ticket_approval_unique_constraint(db_engine, approved):
    from sqlalchemy.exc import IntegrityError
    with Session(db_engine) as s:
        execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        old = s.scalar(select(Ticket))
        values = {column.name: getattr(old, column.name) for column in Ticket.__table__.columns}
        values["ticket_id"] = "TK-another"
        s.add(Ticket(**values))
        with pytest.raises(IntegrityError):
            s.commit()


def test_database_failure_rolls_back_ticket_and_success_record(db_engine, approved):
    with Session(db_engine) as s:
        with patch.object(s, "flush", side_effect=OperationalError("statement", {}, RuntimeError("secret"))):
            with pytest.raises(OperationalError):
                execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with Session(db_engine) as s:
        assert s.scalar(select(func.count()).select_from(Ticket)) == 0
        assert s.get(TicketExecution, "approval-1") is None


def test_parallel_sessions_create_only_one_ticket(db_engine, approved):
    def run():
        with Session(db_engine) as s:
            return execute_ticket(s, "approval-1", approved, "reviewer-demo-001")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0].ticket.ticket_id == results[1].ticket.ticket_id
    assert sorted(r.reused for r in results) == [False, True]


def test_api_execution_query_repeat_and_permission(db_engine, approved):
    from contextlib import contextmanager
    @contextmanager
    def fake_graph():
        yield SimpleNamespace(get_state=lambda config: SimpleNamespace(values=approved))
    def db():
        with Session(db_engine) as s:
            yield s
    app.dependency_overrides[get_db] = db
    headers = {"X-Demo-User": "reviewer-demo-001"}
    try:
        with TestClient(app) as client, patch("app.api.approvals.open_review_graph", fake_graph):
            blocked = client.post("/api/v1/approvals/approval-1/execute", headers={"X-Demo-User": "employee-demo-001"})
            assert blocked.status_code == 403
            response = client.post("/api/v1/approvals/approval-1/execute", headers=headers)
            assert response.status_code == 200
            ticket_id = response.json()["ticket"]["ticket_id"]
            assert client.post("/api/v1/approvals/approval-1/execute", headers=headers).json()["reused"] is True
            assert client.get(f"/api/v1/tickets/{ticket_id}", headers=headers).json()["status"] == "open"
            assert client.get("/api/v1/approvals/approval-1/execution", headers=headers).json()["status"] == "success"
            assert client.get("/api/v1/tickets/missing", headers=headers).status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_api_unapproved_task_is_conflict(db_engine, approved, status):
    from contextlib import contextmanager
    approved["proposal"]["approval_status"] = status
    @contextmanager
    def graph():
        yield SimpleNamespace(get_state=lambda config: SimpleNamespace(values=approved))
    def db():
        with Session(db_engine) as s:
            yield s
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as client, patch("app.api.approvals.open_review_graph", graph):
            response = client.post("/api/v1/approvals/a/execute", headers={"X-Demo-User": "reviewer-demo-001"})
            assert response.status_code == 409
        with Session(db_engine) as s:
            assert s.scalar(select(func.count()).select_from(Ticket)) == 0
    finally:
        app.dependency_overrides.pop(get_db, None)
