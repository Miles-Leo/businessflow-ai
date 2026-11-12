# 模块职责：手工调试入口：try_mcp；按需显式执行，运行前核对外部服务与演示数据。
"""独立 stdio MCP Client 演示；默认以非法编号验证工具错误分支。"""
import asyncio
import sys
from pathlib import Path
from mcp import Client, StdioServerParameters


def print_tool_result(result) -> None:
    """先检查 MCP 工具错误，再解释本项目的业务结果。"""
    if result.is_error:
        print("工具调用失败，请检查参数或服务状态")
        return

    data = result.structured_content
    if not isinstance(data, dict):
        print("工具未返回有效的结构化结果")
        return

    status = data.get("status")
    if status == "success":
        order = data.get("data")
        if not isinstance(order, dict):
            print("工具未返回有效的订单数据")
            return
        print("订单查询成功：", order)
    elif status == "not_found":
        print("订单不存在")
    elif status == "failed":
        print("业务查询失败")
    else:
        print("工具返回了未知业务状态")


async def main() -> None:
    project_root = Path(__file__).resolve().parents[1]

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(project_root),
    )

    # 下一步在这里连接 Client
    async with Client(params) as client:
        result = await client.list_tools()


        # 打印每个工具的 name
        for tool in result.tools:
            print(tool.name)
        result = await client.call_tool(
            "lookup_order",
            {"order_id": "123"},
        )

        print_tool_result(result)


if __name__ == "__main__":
    asyncio.run(main())
