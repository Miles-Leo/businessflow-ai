import sys
from types import ModuleType
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from app.ai.task_nodes import run_query


def test_tool_failure_is_not_hidden_by_final_model_reply(fake_graph):
    from langchain_core.messages import ToolMessage
    fake_graph.invoke.return_value = {"messages": [
        ToolMessage(content='{"status":"failed","data":null}', tool_call_id="demo"),
        AIMessage(content="目前无法查询"),
    ]}
    result = run_query({"user_input": "查询订单"})
    assert result["answer"] is None and result["error"]


@pytest.fixture
def fake_graph(monkeypatch):
    module = ModuleType("app.ai.agent_graph")
    module.graph = Mock()
    monkeypatch.setitem(sys.modules, "app.ai.agent_graph", module)
    return module.graph


def test_query_success_preserves_input(fake_graph):
    state = {"user_input": "查询订单 BF2026001", "answer": None}
    original = state.copy()
    fake_graph.invoke.return_value = {"messages": [AIMessage(content="订单尚未发货")]}

    assert run_query(state) == {"answer": "订单尚未发货", "error": None}
    assert state == original
    supplied = fake_graph.invoke.call_args.args[0]["messages"]
    assert len(supplied) == 1
    assert isinstance(supplied[0], HumanMessage)
    assert supplied[0].content == state["user_input"]
    assert fake_graph.invoke.call_args.kwargs == {"config": {"recursion_limit": 10}}


@pytest.mark.parametrize("messages", [
    [],
    [HumanMessage(content="不是最终回答")],
    [AIMessage(content="")],
    [AIMessage(content="  ")],
    [AIMessage(content=[{"type": "text", "text": "非字符串内容"}])],
    [AIMessage(content="处理中", tool_calls=[{"name": "lookup_order", "args": {}, "id": "call-1"}])],
])
def test_rejects_incomplete_reply(fake_graph, messages):
    fake_graph.invoke.return_value = {"messages": messages}
    assert run_query({"user_input": "查询订单"}) == {
        "answer": None, "error": "查询未返回完整文本回复",
    }


@pytest.mark.parametrize("failure,expected", [
    (GraphRecursionError("sensitive details"), "查询超过执行步数限制，请简化请求"),
    (RuntimeError("sensitive details"), "查询暂时不可用，请稍后重试"),
])
def test_execution_failure_is_safe(fake_graph, failure, expected):
    fake_graph.invoke.side_effect = failure
    assert run_query({"user_input": "查询订单"}) == {"answer": None, "error": expected}


def test_graph_import_failure_is_safe(monkeypatch):
    # None 模拟导入不可用，避免初始化真实模型。
    monkeypatch.setitem(sys.modules, "app.ai.agent_graph", None)
    assert run_query({"user_input": "查询订单"}) == {
        "answer": None, "error": "查询暂时不可用，请稍后重试",
    }
