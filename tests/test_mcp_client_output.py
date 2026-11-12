from types import SimpleNamespace

import pytest

from scripts.try_mcp import print_tool_result


@pytest.mark.parametrize("is_error,data,expected", [
    (True, None, "工具调用失败，请检查参数或服务状态"),
    (False, None, "工具未返回有效的结构化结果"),
    (False, [], "工具未返回有效的结构化结果"),
    (False, {}, "工具返回了未知业务状态"),
    (False, {"status": "unexpected"}, "工具返回了未知业务状态"),
    (False, {"status": "not_found", "data": None}, "订单不存在"),
    (False, {"status": "failed", "error": "secret-token"}, "业务查询失败"),
    (False, {"status": "success", "data": None}, "工具未返回有效的订单数据"),
    (False, {"status": "success", "data": {"order_id": "BF2026001"}}, "订单查询成功："),
])
def test_tool_result_output(capsys, is_error, data, expected):
    print_tool_result(SimpleNamespace(is_error=is_error, structured_content=data))
    output = capsys.readouterr().out
    assert expected in output
    assert "secret-token" not in output


def test_tool_error_takes_priority_over_business_success(capsys):
    print_tool_result(SimpleNamespace(is_error=True, structured_content={"status": "success", "data": {}}))
    assert capsys.readouterr().out.strip() == "工具调用失败，请检查参数或服务状态"
