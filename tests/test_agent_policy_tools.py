from copy import deepcopy
from importlib import import_module
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


def load_agent():
    with patch("app.ai.model.create_chat_model"):
        return import_module("app.ai.agent")


def test_mixed_order_and_policy_calls_keep_matching_ids():
    agent = load_agent()
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "lookup_order", "args": {"order_id": "BF2026001"}, "id": "order-call"},
        {"name": "search_policy", "args": {"question": "审核要求？"}, "id": "policy-call"},
    ])]}
    original = deepcopy(state)
    order_result = {"status": "success", "data": {"order_id": "BF2026001"}, "error": None}
    policy_result = {"status": "success", "data": [{"text": "批准后才能创建", "section": "AS-05", "source": "policy.md"}], "error": None}
    with patch.object(agent, "order_lookup_tool") as order, patch.object(agent, "policy_search_tool") as policy:
        order.invoke.return_value = order_result
        policy.invoke.return_value = policy_result
        update = agent.execute_tools(state)
    order.invoke.assert_called_once_with({"order_id": "BF2026001"})
    policy.invoke.assert_called_once_with({"question": "审核要求？"})
    assert [message.tool_call_id for message in update["messages"]] == ["order-call", "policy-call"]
    assert all(isinstance(message, ToolMessage) for message in update["messages"])
    assert [json.loads(message.content) for message in update["messages"]] == [order_result, policy_result]
    assert state == original


@pytest.mark.parametrize("args", [{}, {"question": " "}, {"question": "a" * 2001}])
def test_invalid_policy_args_skip_retrieval_and_allow_next_order(args):
    agent = load_agent()
    from app.ai.tools import policy_search_tool
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "search_policy", "args": args, "id": "invalid-policy"},
        {"name": "lookup_order", "args": {"order_id": "BF2026001"}, "id": "valid-order"},
    ])]}
    with patch.object(agent, "policy_search_tool", policy_search_tool), patch.object(
        agent, "order_lookup_tool"
    ) as order, patch("app.ai.tools.retrieve_policy") as retrieve:
        order.invoke.return_value = {"status": "not_found", "data": None, "error": "订单不存在"}
        update = agent.execute_tools(state)
    retrieve.assert_not_called()
    order.invoke.assert_called_once_with({"order_id": "BF2026001"})
    assert len(update["messages"]) == 2
    assert update["messages"][0].tool_call_id == "invalid-policy"
    failure = json.loads(update["messages"][0].content)
    assert failure["status"] == "failed"
    assert failure["data"] == []
    assert failure["error"]
    assert update["messages"][1].tool_call_id == "valid-order"


@pytest.mark.parametrize("status", ["not_found", "failed"])
def test_policy_failure_status_is_preserved(status):
    agent = load_agent()
    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "search_policy", "args": {"question": "规则？"}, "id": "policy-call"},
    ])]}
    result = {"status": status, "data": [], "error": "无法提供政策依据"}
    with patch.object(agent, "policy_search_tool") as policy:
        policy.invoke.return_value = result
        update = agent.execute_tools(state)
    assert json.loads(update["messages"][0].content) == result
