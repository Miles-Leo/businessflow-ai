import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.ai.mcp import parse_tool_result, query_order_via_mcp


@pytest.mark.parametrize("is_error,data", [
    (True, None), (True, {"status": "success", "data": {}}),
    (False, None), (False, []), (False, {}),
    (False, {"status": "unexpected"}), (False, {"status": "success", "data": None}),
])
def test_invalid_results_fail_safely(is_error, data, capsys):
    result = parse_tool_result(SimpleNamespace(is_error=is_error, structured_content=data))
    assert result["status"] == "failed" and result["data"] is None and result["error"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("status", ["success", "not_found", "failed"])
def test_valid_result_preserves_all_fields(status):
    data = {"status": status, "data": {"order_id": "BF2026001"} if status == "success" else None,
            "error": None if status == "success" else "安全说明", "assessment": {"checked_at": "demo"}}
    assert parse_tool_result(SimpleNamespace(is_error=False, structured_content=data)) == data


def test_client_uses_project_root_and_returns_after_context_closes():
    data = {"status": "success", "data": {"order_id": "BF2026001"}, "error": None}
    client = AsyncMock()
    client.call_tool.return_value = SimpleNamespace(is_error=False, structured_content=data)
    context = AsyncMock()
    context.__aenter__.return_value = client
    factory = Mock(return_value=context)
    with patch("app.ai.mcp.Client", factory):
        result = asyncio.run(query_order_via_mcp("BF2026001"))
    assert result == data
    assert factory.call_args.args[0].cwd == str(Path(__file__).resolve().parents[1])
    assert factory.call_args.kwargs == {"read_timeout_seconds": 30}
    client.call_tool.assert_awaited_once_with("lookup_order", {"order_id": "BF2026001"})
    context.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("stage", ["create", "connect", "call", "close"])
def test_connection_and_call_failures_are_safe(stage):
    client = AsyncMock()
    client.call_tool.return_value = SimpleNamespace(is_error=False, structured_content={"status": "not_found", "data": None})
    context = AsyncMock()
    context.__aenter__.return_value = client
    failure = RuntimeError("secret-token private path")
    if stage == "connect":
        context.__aenter__.side_effect = failure
    elif stage == "call":
        client.call_tool.side_effect = ExceptionGroup("private errors", [failure])
    elif stage == "close":
        context.__aexit__.side_effect = failure
    factory = Mock(side_effect=failure) if stage == "create" else Mock(return_value=context)
    with patch("app.ai.mcp.Client", factory):
        result = asyncio.run(query_order_via_mcp("BF2026001"))
    assert result == {"status": "failed", "data": None, "error": "订单查询连接或调用失败，请稍后重试"}
    if stage in {"call", "close"}:
        context.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("stage", ["connect", "call"])
def test_total_timeout_cancels_wait_and_closes_entered_context(stage):
    async def scenario():
        client = AsyncMock()
        context = AsyncMock()
        context.__aenter__.return_value = client
        cancelled = asyncio.Event()

        async def wait_forever(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        if stage == "connect":
            context.__aenter__.side_effect = wait_forever
        else:
            client.call_tool.side_effect = wait_forever
        with patch("app.ai.mcp.Client", return_value=context):
            result = await query_order_via_mcp("BF2026001", timeout_seconds=0.05)
        assert result == {"status": "failed", "data": None, "error": "订单查询超时，请稍后重试"}
        assert cancelled.is_set()
        if stage == "call":
            context.__aexit__.assert_awaited_once()
    asyncio.run(scenario())


def test_caller_cancellation_propagates_and_closes_context():
    async def scenario():
        started = asyncio.Event()
        client = AsyncMock()
        context = AsyncMock()
        context.__aenter__.return_value = client

        async def wait_forever(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        client.call_tool.side_effect = wait_forever
        with patch("app.ai.mcp.Client", return_value=context):
            task = asyncio.create_task(query_order_via_mcp("BF2026001"))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        context.__aexit__.assert_awaited_once()
    asyncio.run(scenario())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_does_not_start_client(timeout):
    with patch("app.ai.mcp.Client") as factory:
        with pytest.raises(ValueError):
            asyncio.run(query_order_via_mcp("BF2026001", timeout_seconds=timeout))
        factory.assert_not_called()
