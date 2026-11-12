from copy import deepcopy
from importlib import import_module
import json
from unittest.mock import Mock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError


def load_graph():
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")
        graph = import_module("app.ai.agent_graph").graph
    return agent, graph


def test_agent_direct_response_skips_tools():
    agent, graph = load_graph()
    reply = AIMessage(content="你好")
    state = {"messages": [HumanMessage(content="你好")]}
    with patch.object(agent, "model_with_tools") as model, patch.object(
        agent, "order_lookup_tool"
    ) as tool:
        model.invoke.return_value = reply
        result = graph.invoke(state)
    model.invoke.assert_called_once()
    tool.invoke.assert_not_called()
    assert [m.type for m in result["messages"]] == ["human", "ai"]
    assert result["messages"][-1].content == "你好"


def test_agent_multiple_tools_then_final_reply():
    agent, graph = load_graph()
    requests = AIMessage(content="", tool_calls=[
        {"name": "lookup_order", "args": {"order_id": number}, "id": f"call-{i}"}
        for i, number in enumerate(["BF2026001", "BF9999999"])
    ])
    tool_results = [
        {"status": "success", "data": {"order_id": "BF2026001"}, "error": None},
        {"status": "not_found", "data": None, "error": "订单不存在"},
    ]
    history_seen = []

    def reply(messages):
        history_seen.append(deepcopy(messages))
        return requests if len(history_seen) == 1 else AIMessage(content="查询结束")

    with patch.object(agent, "model_with_tools") as model, patch.object(
        agent, "order_lookup_tool"
    ) as tool:
        model.invoke.side_effect = reply
        tool.invoke.side_effect = tool_results
        result = graph.invoke({"messages": [HumanMessage(content="查询两个订单")]})

    assert model.invoke.call_count == 2
    assert tool.invoke.call_count == 2
    for sent in history_seen:
        assert sent[0].type == "system"
        assert sent[0].content == agent.ORDER_AGENT_SYSTEM_PROMPT
        assert sum(m.type == "system" for m in sent) == 1
    assert [m.type for m in history_seen[1]] == ["system", "human", "ai", "tool", "tool"]
    for i, message in enumerate(history_seen[1][3:]):
        assert isinstance(message, ToolMessage)
        assert message.tool_call_id == f"call-{i}"
        assert json.loads(message.content) == tool_results[i]
    assert [m.type for m in result["messages"]] == ["human", "ai", "tool", "tool", "ai"]
    assert result["messages"][-1].content == "查询结束"


def test_agent_repeated_calls_stop_at_recursion_limit():
    agent, graph = load_graph()

    def keep_calling(messages):
        return AIMessage(content="", tool_calls=[{
            "name": "lookup_order", "args": {"order_id": "BF2026001"},
            "id": f"call-{len(messages)}",
        }])

    with patch.object(agent, "model_with_tools") as model, patch.object(
        agent, "order_lookup_tool"
    ) as tool:
        model.invoke.side_effect = keep_calling
        tool.invoke.return_value = {"status": "not_found", "data": None, "error": "订单不存在"}
        with pytest.raises(GraphRecursionError):
            graph.invoke({"messages": [HumanMessage(content="查询订单")]}, config={"recursion_limit": 4})


@pytest.mark.parametrize("policy_status", ["success", "not_found", "failed"])
def test_agent_combines_order_and_policy_results(policy_status):
    agent, graph = load_graph()
    request = AIMessage(content="", tool_calls=[
        {"name": "lookup_order", "args": {"order_id": "BF2026001"}, "id": "order-call"},
        {"name": "search_policy", "args": {"question": "超期未发货政策"}, "id": "policy-call"},
    ])
    order_result = {"status": "success", "data": {"order_id": "BF2026001", "shipped_at": None}, "error": None}
    policy_result = {
        "status": policy_status,
        "data": [{"text": "需负责人批准", "section": "AS-05", "source": "policy.md"}] if policy_status == "success" else [],
        "error": None if policy_status == "success" else "政策依据暂不可用",
    }
    seen = []

    def respond(messages):
        seen.append(deepcopy(messages))
        return request if len(seen) == 1 else AIMessage(content="模拟最终回复")

    with patch.object(agent, "model_with_tools") as model, patch.object(
        agent, "order_lookup_tool"
    ) as order, patch.object(agent, "policy_search_tool") as policy:
        model.invoke.side_effect = respond
        order.invoke.return_value = order_result
        policy.invoke.return_value = policy_result
        result = graph.invoke({"messages": [HumanMessage(content="查询订单及政策")]})

    assert model.invoke.call_count == 2
    order.invoke.assert_called_once_with({"order_id": "BF2026001"})
    policy.invoke.assert_called_once_with({"question": "超期未发货政策"})
    assert [m.type for m in seen[1]] == ["system", "human", "ai", "tool", "tool"]
    assert [m.tool_call_id for m in seen[1][3:]] == ["order-call", "policy-call"]
    assert [json.loads(m.content) for m in seen[1][3:]] == [order_result, policy_result]
    assert [m.type for m in result["messages"]] == ["human", "ai", "tool", "tool", "ai"]
    assert result["messages"][-1].content == "模拟最终回复"
