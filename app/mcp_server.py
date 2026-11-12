# 模块职责：MCP stdio 只读订单服务；stdout 专用于协议，诊断不得污染协议输出。
"""MCP 只读订单查询服务：复用订单校验和查询实现。

使用本项目已安装的 mcp 2.x API，不使用旧版 FastMCP 示例。
已注册只读订单查询工具，执行模块时启动 stdio 服务；导入模块不会访问数据库。
"""

from mcp.server import MCPServer



server = MCPServer("BusinessFlow Orders")

@server.tool("lookup_order")
def lookup_order_mcp(order_id: str) -> dict[str, object]:
    """只读查询虚构订单；不创建工单、不修改订单、不执行审核。"""



    # 注意：不要复制 SQL 查询逻辑，也不要把查询异常改成 not_found。
    from app.ai.tools import OrderLookupInput, lookup_order
    validated = OrderLookupInput(order_id=order_id)
    return lookup_order(validated.order_id)

def main() -> None:

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
