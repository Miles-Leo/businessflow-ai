from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from app.main import app

client = TestClient(app, headers={"X-Demo-User": "employee-demo-001"})


def test_query_success():
    graph = Mock()
    graph.invoke.return_value = {"messages": [AIMessage(content="订单尚未发货")]}
    with patch("app.api.agent.get_agent_graph", return_value=graph):
        response = client.post("/api/v1/agent/query", json={"user_input": "查询订单 BF2026001"})
    assert response.status_code == 200
    assert response.json() == {"answer": "订单尚未发货"}
    state = graph.invoke.call_args.args[0]
    assert len(state["messages"]) == 1
    assert state["messages"][0].content == "查询订单 BF2026001"
    assert graph.invoke.call_args.kwargs["config"] == {"recursion_limit": 10}


@pytest.mark.parametrize("payload", [{}, {"user_input": ""}, {"user_input": "  "}, {"user_input": "a" * 2001}])
def test_invalid_input(payload):
    with patch("app.api.agent.get_agent_graph") as factory:
        response = client.post("/api/v1/agent/query", json=payload)
    assert response.status_code == 422
    factory.assert_not_called()


@pytest.mark.parametrize("failure,status", [(RuntimeError("secret"), 502), (GraphRecursionError("secret"), 503)])
def test_execution_error(failure, status):
    graph = Mock()
    graph.invoke.side_effect = failure
    with patch("app.api.agent.get_agent_graph", return_value=graph):
        response = client.post("/api/v1/agent/query", json={"user_input": "查询订单"})
    assert response.status_code == status
    assert "secret" not in response.text


def test_configuration_error():
    with patch("app.api.agent.get_agent_graph", side_effect=KeyError("secret")):
        response = client.post("/api/v1/agent/query", json={"user_input": "查询订单"})
    assert response.status_code == 503
    assert "secret" not in response.text


def test_unfinished_reply():
    graph = Mock()
    graph.invoke.return_value = {"messages": [AIMessage(content="", tool_calls=[{"name": "lookup_order", "args": {}, "id": "test"}])]}
    with patch("app.api.agent.get_agent_graph", return_value=graph):
        response = client.post("/api/v1/agent/query", json={"user_input": "查询订单"})
    assert response.status_code == 502
