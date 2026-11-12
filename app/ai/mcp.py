# 模块职责：MCP 只读订单客户端，已由 Agent 订单工具调用；负责连接、超时和结果归一化。
"""MCP 只读查询适配器；由 Agent 的订单工具执行入口调用。"""
import asyncio
import math
import sys
from pathlib import Path
from mcp import Client, StdioServerParameters

def parse_tool_result(result) -> dict[str, object]:
    """将 MCP 结果转换为业务字典，不打印业务数据。"""
    if result.is_error:
        return {"status": "failed", "data": None, "error": "订单查询工具调用失败"}

    data = result.structured_content
    if not isinstance(data, dict):
        return {"status": "failed", "data": None, "error": "订单查询工具未返回有效结果"}

    status = data.get("status")
    if status == "success":
        if not isinstance(data.get("data"), dict):
            return {"status": "failed", "data": None, "error": "订单查询工具未返回有效订单数据"}
    elif status not in ("not_found", "failed"):
        return {"status": "failed", "data": None, "error": "订单查询工具返回未知业务状态"}
    return data

# 维护约束：总超时包含连接与调用；取消后等待协议资源清理，不声称严格定时杀进程。
async def query_order_via_mcp(
    order_id: str, *, timeout_seconds: float = 30,
) -> dict[str, object]:
    """限制连接和查询的总等待时间；退出上下文清理连接，不自动重试。

    超时会发起取消并等待 SDK 清理，实际返回时间可能包含清理耗时。
    调用方主动取消应继续向上传播，而不是伪装成普通查询失败。
    """
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须是有限正数")
    project_root = Path(__file__).resolve().parents[2]

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(project_root),
    )

    deadline = asyncio.timeout(timeout_seconds)
    try:
        async with deadline:
            async with Client(params, read_timeout_seconds=timeout_seconds) as client:
                result = await client.call_tool(
                    "lookup_order",
                    {"order_id": order_id},
                )
                data = parse_tool_result(result)
        return data
    except TimeoutError:
        return {"status": "failed", "data": None, "error": "订单查询超时，请稍后重试"}
    except Exception:
        # SDK 清理时可能将异常包装成 ExceptionGroup，也不能暴露其原文。
        if deadline.expired():
            return {"status": "failed", "data": None, "error": "订单查询超时，请稍后重试"}
        return {"status": "failed", "data": None, "error": "订单查询连接或调用失败，请稍后重试"}
