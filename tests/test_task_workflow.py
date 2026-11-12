from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.ai.task_graph import build_task_graph
from app.ai.task_nodes import TaskIntent, begin_review, parse_task
from app.db.init_tasks import initialize_tasks
from app.db.models import AgentTask, Order
from app.services.review_runtime import open_review_graph

EMPLOYEE = {"X-Demo-User": "employee-demo-001"}
MANAGER = {"X-Demo-User": "reviewer-demo-001"}


def test_task_and_direct_api_share_business_dedup(client, proposal, review_runtime):
    first = begin_review(initial(task_id='first', order_id='BF2026001', proposal=proposal))
    assert first['error'] is None
    second = begin_review(initial(task_id='second', order_id='BF2026001', proposal=proposal))
    assert second['approval_id'] is None and '同类申请' in second['error']
    with patch('app.api.approvals.prepare_proposal', return_value=proposal):
        response = client.post('/api/v1/approvals', headers=EMPLOYEE, json={'order_id':'BF2026001'})
    assert response.status_code == 409
    with review_runtime() as graph:
        assert not graph.get_state({'configurable':{'thread_id':'second'}}).values


def test_concurrent_applications_only_start_one_review(proposal, review_runtime):
    from concurrent.futures import ThreadPoolExecutor
    def apply(task_id):
        return begin_review(initial(task_id=task_id, order_id='BF2026001', proposal=proposal))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, ['concurrent-first', 'concurrent-second']))
    assert sum(result['approval_id'] is not None for result in results) == 1
    with review_runtime() as graph:
        ids = {snapshot.config['configurable']['thread_id'] for snapshot in graph.checkpointer.list(None)}
    assert len(ids) == 1


def initial(**changes):
    return {"task_id": "task-test", "user_input": "生成待审核建议",
            "intent": "unknown", "order_id": None, "approval_id": None,
            "proposal": None, "answer": None, "error": None, **changes}


@pytest.fixture
def proposal():
    return {"order_id": "BF2026001", "issue_type": "shipping_delay",
            "description": "订单尚未发货，建议核查发货进展。",
            "checked_at": "2026-11-08T08:00:00+00:00", "approval_status": "pending",
            "policy_sources": [{"document_title": "测试政策", "section": f"{code}：测试条款",
                                "source": "policy.md", "chunk_id": code}
                               for code in ("AS-04", "AS-05")]}


@pytest.fixture
def review_runtime(tmp_path, monkeypatch, db_engine):
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=db_engine))
    database = tmp_path / "reviews.db"
    database.touch()

    @contextmanager
    def factory():
        with open_review_graph(database) as graph:
            yield graph

    monkeypatch.setattr("app.services.review_runtime.open_review_graph", factory)
    monkeypatch.setattr("app.api.approvals.open_persistent_review_graph", factory)
    return factory


def create(client, question="查询订单 BF2026001"):
    response = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json={"user_input": question})
    assert response.status_code == 201
    return response.json()["task_id"]


def test_parser_uses_schema_and_preserves_input():
    model = Mock()
    model.with_structured_output.return_value.invoke.return_value = TaskIntent(intent="query")
    state = initial(user_input="售后政策是什么")
    with patch("app.ai.task_nodes.create_chat_model", return_value=model):
        assert parse_task(state) == {"intent": "query", "order_id": None, "error": None}
    model.with_structured_output.assert_called_once_with(TaskIntent)
    messages = model.with_structured_output.return_value.invoke.call_args.args[0]
    assert messages[0]["role"] == "system" and "JSON" in messages[0]["content"]
    assert "售后政策是什么" in messages[1]["content"]
    assert state["intent"] == "unknown"


def test_parser_failure_is_safe():
    with patch("app.ai.task_nodes.create_chat_model", side_effect=RuntimeError("secret")):
        result = parse_task(initial())
    assert result["error"] and "secret" not in result["error"]


@pytest.mark.parametrize("intent,order_id,expected", [
    ("query", None, "query"), ("create_proposal", "BF2026001", "proposal"),
    ("create_proposal", None, "missing"), ("unknown", None, "unsupported"),
])
def test_graph_routes_without_unwanted_tools(intent, order_id, expected, proposal):
    with patch("app.ai.task_nodes.parse_task", return_value={"intent": intent, "order_id": order_id}), \
         patch("app.ai.task_nodes.run_query", return_value={"answer": "查询回答", "error": None}) as query, \
         patch("app.ai.task_nodes.generate_proposal", return_value={"proposal": proposal, "error": None}) as generate, \
         patch("app.ai.task_nodes.begin_review", return_value={"approval_id": "task-test", "error": None}) as review:
        result = build_task_graph().invoke(initial())
    assert query.call_count == (expected == "query")
    assert generate.call_count == (expected == "proposal")
    assert review.call_count == (expected == "proposal")
    assert bool(result["error"]) == (expected in {"missing", "unsupported"})


@pytest.mark.parametrize("where", ["parse", "proposal"])
def test_graph_stops_on_failure(where):
    parsed = {"intent": "create_proposal", "order_id": "BF2026001", "error": "解析失败" if where == "parse" else None}
    with patch("app.ai.task_nodes.parse_task", return_value=parsed), \
         patch("app.ai.task_nodes.generate_proposal", return_value={"proposal": None, "error": "生成失败"}) as generate, \
         patch("app.ai.task_nodes.begin_review") as review:
        result = build_task_graph().invoke(initial())
    assert result["error"]
    assert generate.call_count == (where == "proposal")
    review.assert_not_called()


def test_begin_review_is_persistent_and_does_not_restart(proposal, review_runtime):
    state = initial(order_id="BF2026001", proposal=proposal)
    original = deepcopy(state)
    first = begin_review(state)
    assert first["approval_id"] == "task-test" and first["error"] is None
    with patch("app.services.approval.start_review") as start:
        assert begin_review(state)["approval_id"] == first["approval_id"]
        assert begin_review({**state, "approval_id": first["approval_id"]})["error"] is None
        start.assert_not_called()
    assert state == original
    with review_runtime() as graph:
        assert graph.get_state({"configurable": {"thread_id": "task-test"}}).next == ("review",)


@pytest.mark.parametrize("kind", ["missing", "approved", "wrong_order"])
def test_invalid_proposal_does_not_open_review(kind, proposal):
    if kind == "approved":
        proposal["approval_status"] = "approved"
    if kind == "wrong_order":
        proposal["order_id"] = "BF2026002"
    with patch("app.services.review_runtime.open_review_graph") as factory:
        result = begin_review(initial(order_id="BF2026001", proposal=None if kind == "missing" else proposal))
    assert result["error"] and result["approval_id"] is None
    factory.assert_not_called()


def test_query_run_persists_answer_and_is_not_repeated(client, db_engine):
    task_id = create(client)
    with patch("app.ai.task_nodes.parse_task", return_value={"intent": "query", "order_id": "BF2026001"}), \
         patch("app.ai.task_nodes.run_query", return_value={"answer": "订单尚未发货", "error": None}) as query:
        response = client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE)
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["answer"] == "订单尚未发货"
        again = client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE)
        assert again.json() == response.json()
        query.assert_called_once()
    with Session(db_engine) as session:
        assert session.get(AgentTask, task_id).answer == "订单尚未发货"


@pytest.mark.parametrize("action", ["run", "refresh"])
def test_run_refresh_auth_and_ownership(client, action):
    task_id = create(client)
    with patch("app.services.tasks.get_task_graph") as factory:
        assert client.post(f"/api/v1/agent/tasks/{task_id}/{action}").status_code == 401
        assert client.post(f"/api/v1/agent/tasks/{task_id}/{action}", headers=MANAGER).status_code == 404
        assert client.post(f"/api/v1/agent/tasks/missing/{action}", headers=EMPLOYEE).status_code == 404
        factory.assert_not_called()


def test_running_task_cannot_be_run_twice(client, db_engine):
    task_id = create(client)
    with Session(db_engine) as session, session.begin():
        session.get(AgentTask, task_id).status = "running"
    with patch("app.services.tasks.get_task_graph") as graph:
        assert client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE).status_code == 409
        graph.assert_not_called()


def test_model_exception_is_persisted_safely(client):
    task_id = create(client)
    with patch("app.services.tasks.get_task_graph", side_effect=RuntimeError("secret")):
        response = client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "secret" not in response.text
    assert client.get(f"/api/v1/agent/tasks/{task_id}", headers=EMPLOYEE).json() == response.json()


@pytest.mark.parametrize("decision", ["approved", "rejected"])
def test_proposal_review_execution_end_to_end(client, proposal, review_runtime, decision):
    task_id = create(client, "如果超期未发货，请为订单 BF2026001 生成待审核建议")
    with patch("app.ai.task_nodes.parse_task", return_value={"intent": "create_proposal", "order_id": "BF2026001"}), \
         patch("app.ai.review.prepare_ticket_proposal_result", return_value=(proposal, "订单查询结果\n订单编号：BF2026001\n订单状态：pending\n超期未发货判定：是", None)):
        run = client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE)
    assert run.status_code == 200
    assert run.json()["status"] == "waiting_approval"
    assert "订单状态：pending" in run.json()["answer"]
    assert run.json()["approval_id"] == task_id
    assert run.json()["ticket_id"] is None
    event_url = f"/api/v1/agent/tasks/{task_id}/events"
    assert [event["event_type"] for event in client.get(event_url, headers=EMPLOYEE).json() if event["event_type"] != "node_result"] == [
        "task_created", "task_started", "review_pending",
    ]
    execution_url = f"/api/v1/approvals/{task_id}/execute"
    assert client.post(execution_url, headers=MANAGER).status_code == 409
    assert client.post(f"/api/v1/approvals/{task_id}/decision", headers=EMPLOYEE,
                       json={"decision": decision}).status_code == 403
    assert client.post(f"/api/v1/approvals/{task_id}/decision", headers=MANAGER,
                       json={"decision": decision}).status_code == 200
    refreshed = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
    assert refreshed.status_code == 200
    assert "订单状态：pending" in refreshed.json()["answer"]
    if decision == "rejected":
        assert refreshed.json()["status"] == "rejected"
        assert client.post(execution_url, headers=MANAGER).status_code == 409
        logged = client.get(event_url, headers=EMPLOYEE).json()
        assert [event["event_type"] for event in logged if event["event_type"] != "node_result"] == [
            "task_created", "task_started", "review_pending", "review_rejected",
        ]
        assert client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE).status_code == 200
        assert client.get(event_url, headers=EMPLOYEE).json() == logged
    else:
        assert refreshed.json()["status"] == "executing"
        assert refreshed.json()["ticket_id"] is None
        assert client.post(execution_url, headers=EMPLOYEE).status_code == 403
        executed = client.post(execution_url, headers=MANAGER)
        assert executed.status_code == 200
        ticket_id = executed.json()["ticket"]["ticket_id"]
        finished = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
        assert finished.status_code == 200 and finished.json()["status"] == "completed"
        assert finished.json()["ticket_id"] == ticket_id
        assert client.post(execution_url, headers=MANAGER).json()["ticket"]["ticket_id"] == ticket_id
        event_url = f"/api/v1/agent/tasks/{task_id}/events"
        logged = client.get(event_url, headers=EMPLOYEE).json()
        assert [event["event_type"] for event in logged if event["event_type"] != "node_result"] == [
            "task_created", "task_started", "review_pending", "review_approved", "ticket_created",
        ]
        client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
        assert client.get(event_url, headers=EMPLOYEE).json() == logged


def test_refresh_recovers_review_after_task_save_was_lost(client, db_engine, proposal, review_runtime):
    task_id = create(client)
    with Session(db_engine) as session, session.begin():
        session.get(AgentTask, task_id).status = "running"
    assert begin_review(initial(task_id=task_id, order_id="BF2026001", proposal=proposal))["error"] is None
    response = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "waiting_approval"
    assert response.json()["approval_id"] == task_id


def test_refresh_without_checkpoint_keeps_uncertain_running_state(client, db_engine, review_runtime):
    task_id = create(client)
    with Session(db_engine) as session, session.begin():
        session.get(AgentTask, task_id).status = "running"
    response = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "running"


def test_additive_schema_setup_preserves_old_rows_and_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE agent_tasks (task_id TEXT PRIMARY KEY, user_input TEXT)"))
        connection.execute(text("INSERT INTO agent_tasks VALUES ('old-task', '旧任务')"))
    initialize_tasks(engine)
    initialize_tasks(engine)
    assert "answer" in {column["name"] for column in inspect(engine).get_columns("agent_tasks")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT user_input, answer FROM agent_tasks")).one() == ("旧任务", None)
    engine.dispose()


def test_refresh_reports_failed_execution(client, db_engine, proposal, review_runtime):
    from datetime import datetime, timezone
    task_id = create(client)
    with patch("app.ai.task_nodes.parse_task", return_value={"intent": "create_proposal", "order_id": "BF2026001"}), \
         patch("app.ai.review.prepare_ticket_proposal_result", return_value=(proposal, "订单查询结果\n订单编号：BF2026001\n订单状态：pending\n超期未发货判定：是", None)):
        assert client.post(f"/api/v1/agent/tasks/{task_id}/run", headers=EMPLOYEE).json()["status"] == "waiting_approval"
    assert client.post(f"/api/v1/approvals/{task_id}/decision", headers=MANAGER,
                       json={"decision": "approved"}).status_code == 200
    with Session(db_engine) as session, session.begin():
        order = session.get(Order, "BF2026001")
        order.status = "shipped"
        order.shipped_at = datetime(2026, 10, 4, 8, tzinfo=timezone.utc)
    assert client.post(f"/api/v1/approvals/{task_id}/execute", headers=MANAGER).status_code == 409
    response = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert response.json()["ticket_id"] is None and response.json()["error"]
    event_url = f"/api/v1/agent/tasks/{task_id}/events"
    logged = client.get(event_url, headers=EMPLOYEE).json()
    assert [event["event_type"] for event in logged if event["event_type"] != "node_result"] == [
        "task_created", "task_started", "review_pending", "review_approved", "ticket_failed",
    ]
    assert client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE).status_code == 200
    assert client.get(event_url, headers=EMPLOYEE).json() == logged


def test_review_failure_does_not_leak_details(proposal):
    with patch("app.services.review_runtime.open_review_graph", side_effect=RuntimeError("secret")):
        result = begin_review(initial(order_id="BF2026001", proposal=proposal))
    assert result["approval_id"] is None and result["error"]
    assert "secret" not in str(result)


def test_review_lock_is_shared_with_api(proposal):
    from app.api.approvals import _review_lock
    from app.services.review_runtime import review_lock
    assert _review_lock is review_lock
    with review_lock, patch("app.services.review_runtime.open_review_graph") as factory:
        assert begin_review(initial(order_id="BF2026001", proposal=proposal))["error"]
        factory.assert_not_called()


def test_refresh_does_not_repeat_query_or_write(client):
    task_id = create(client)
    with patch("app.services.tasks.get_task_graph") as factory, \
         patch("app.services.review_runtime.open_review_graph") as review:
        response = client.post(f"/api/v1/agent/tasks/{task_id}/refresh", headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "created"
    factory.assert_not_called()
    review.assert_not_called()
