from copy import deepcopy
import json
from importlib import import_module
from unittest.mock import Mock, call, patch

import pytest
from sqlalchemy.orm import sessionmaker
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


@pytest.mark.parametrize("invalid_args", [{"order_id": "abc"}, {}])
def test_invalid_tool_parameters_allow_next_call(invalid_args, db_engine):
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")
    from app.ai.tools import order_lookup_tool

    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "lookup_order", "args": invalid_args, "id": "invalid-call"},
        {"name": "lookup_order", "args": {"order_id": "BF2026001"}, "id": "valid-call"},
    ])]}
    original = deepcopy(state)
    with patch.object(agent, "order_lookup_tool", order_lookup_tool), patch(
        "app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)
    ) as factory:
        # Wrap the factory to count connections while using the isolated database.
        with patch("app.ai.tools.SessionLocal", wraps=factory) as counted_factory:
            update = agent.execute_tools(state)

    counted_factory.assert_called_once_with()
    messages = update["messages"]
    assert len(messages) == 2
    assert messages[0].tool_call_id == "invalid-call"
    failure = json.loads(messages[0].content)
    assert failure["status"] == "failed"
    assert failure["data"] is None
    assert "BF" in failure["error"]
    assert messages[1].tool_call_id == "valid-call"
    success = json.loads(messages[1].content)
    assert success["status"] == "success"
    assert success["data"]["order_id"] == "BF2026001"
    assert state == original


@pytest.mark.parametrize("uses_tool", [False, True])
def test_call_model_returns_only_new_message(uses_tool):
    # Mock model creation before importing the node: no credentials or API calls.
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")

    response = AIMessage(
        content="" if uses_tool else "你好",
        tool_calls=[{
            "name": "lookup_order",
            "args": {"order_id": "BF2026001"},
            "id": "call-test",
        }] if uses_tool else [],
    )
    fake_model = Mock()
    fake_model.invoke.return_value = response
    state = {"messages": [HumanMessage(content="查询订单 BF2026001")]}
    original = deepcopy(state)

    with patch.object(agent, "model_with_tools", fake_model):
        result = agent.call_model(state)

    fake_model.invoke.assert_called_once()
    sent = fake_model.invoke.call_args.args[0]
    assert sent[0].type == "system"
    assert sent[0].content == agent.ORDER_AGENT_SYSTEM_PROMPT
    assert sent[1:] == state["messages"]
    assert result == {"messages": [response]}
    assert result["messages"][0] is response
    assert state == original


def test_unknown_tool_returns_error_and_continues():
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")

    state = {"messages": [AIMessage(content="", tool_calls=[
        {"name": "unsupported_tool", "args": {}, "id": "unknown-call"},
        {"name": "lookup_order", "args": {"order_id": "BF2026001"}, "id": "known-call"},
    ])]}
    original = deepcopy(state)
    success = {"status": "success", "data": {"order_id": "BF2026001"}, "error": None}
    with patch.object(agent, "order_lookup_tool") as tool:
        tool.invoke.return_value = success
        update = agent.execute_tools(state)

    tool.invoke.assert_called_once_with({"order_id": "BF2026001"})
    messages = update["messages"]
    assert len(messages) == 2
    assert messages[0].tool_call_id == "unknown-call"
    assert json.loads(messages[0].content) == {
        "status": "failed", "data": None, "error": "不支持的工具",
    }
    assert messages[1].tool_call_id == "known-call"
    assert json.loads(messages[1].content) == success
    assert state == original


@pytest.mark.parametrize("call_count", [0, 1, 2])
def test_execute_tools_preserves_history_and_matches_call_ids(call_count):
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")

    calls = [
        {"name": "lookup_order", "args": {"order_id": number}, "id": f"call-{index}"}
        for index, number in enumerate(["BF2026001", "BF9999999"][:call_count])
    ]
    results = [
        {"status": "success", "data": {"order_id": "BF2026001"}, "error": None},
        {"status": "not_found", "data": None, "error": "订单不存在"},
    ][:call_count]
    state = {"messages": [
        HumanMessage(content="查询订单"), AIMessage(content="", tool_calls=calls),
    ]}
    original = deepcopy(state)
    with patch.object(agent, "order_lookup_tool") as tool:
        tool.invoke.side_effect = results
        update = agent.execute_tools(state)

    assert set(update) == {"messages"}
    assert len(update["messages"]) == call_count
    assert tool.invoke.call_args_list == [call(item["args"]) for item in calls]
    for message, request, expected in zip(update["messages"], calls, results):
        assert isinstance(message, ToolMessage)
        assert message.tool_call_id == request["id"]
        assert json.loads(message.content) == expected
    assert state == original
