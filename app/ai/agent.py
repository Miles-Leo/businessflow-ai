# 模块职责：只读 Agent 工具循环；白名单分发工具，并以 tool_call_id 关联每一条工具响应。
import json
import asyncio
from pydantic import ValidationError
from langchain_core.messages import ToolMessage
from langchain_core.messages import SystemMessage
from app.ai.prompts import ORDER_AGENT_SYSTEM_PROMPT
from app.ai.state import OrderAgentState
from app.ai.model import create_chat_model
from app.ai.tools import policy_search_tool, OrderLookupInput, customer_lookup_tool
from langchain_core.tools import StructuredTool
from app.ai.mcp import query_order_via_mcp
from app.services.trace import record_step


def lookup_order_using_mcp(order_id: str) -> dict[str, object]:
    """只读查询订单；通过本地 MCP Server 获取事实，不创建或修改订单。"""
    return asyncio.run(query_order_via_mcp(order_id))


order_lookup_tool = StructuredTool.from_function(
    func=lookup_order_using_mcp, name="lookup_order", args_schema=OrderLookupInput,
)


model = create_chat_model()
model_with_tools = model.bind_tools(
    [order_lookup_tool, policy_search_tool, customer_lookup_tool]
)

def call_model(state: OrderAgentState) -> dict[str, object]:
    #定义模型消息列表
    model_messages = [
        SystemMessage(content=ORDER_AGENT_SYSTEM_PROMPT),
        *state["messages"],
    ]
    #调用模型
    response = model_with_tools.invoke(
        model_messages,
    )
    #返回模型回复
    return {"messages": [response]}


# 维护约束：白名单分发只读工具；每个调用都必须返回匹配原调用编号的 ToolMessage。
def execute_tools(state: OrderAgentState) -> dict[str, object]:



    messages = state["messages"]
    response = messages[-1]
    tool_messages = []

    if response.tool_calls:
        # 遍历每个工具调用
        for tool_call in response.tool_calls:
            if tool_call["name"] == "lookup_order":    # 订单查询工具
                try:
                    # 执行工具
                    result = order_lookup_tool.invoke(tool_call["args"])
                except ValidationError:
                    result = {
                        "status": "failed",
                        "data": None,
                        "error": "传入参数错误,正确格式为'BF'+七位数字,如'BF2026001'",
                    }

            elif tool_call["name"] == "lookup_customer":
                try:
                    result = customer_lookup_tool.invoke(tool_call["args"])
                except ValidationError:
                    result = {"status": "failed", "data": None, "error": "客户编号格式无效"}
            elif tool_call["name"] == "search_policy":# 政策检索工具
                try:
                    # 执行工具
                    result = policy_search_tool.invoke(tool_call["args"])
                except ValidationError:
                    result = {
                        "status": "failed",
                        "data": [],
                        "error": "政策问题不能为空，且不能超过 2000 字符",
                    }
            else:
                result = {
                    "status": "failed",
                    "data": None,
                    "error": "不支持的工具",
                }
            record_step(tool_call["name"], result.get("status") != "success", tool=True)
            # 构造 ToolMessage
            tool_messages += [ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call["id"],
            )]

    #最终返回工具消息ToolMessage列表
    return {"messages": tool_messages}


from typing import Literal

# 路由模型回复到工具或结束
def route_after_model(
    state: OrderAgentState,
) -> Literal["tools", "end"]:
    # 读取最后一条模型消息
    # 有工具调用返回 "tools"，否则返回 "end"
    response = state["messages"][-1]
    if response.tool_calls:
        return "tools"
    else:
        return "end"
