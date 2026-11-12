# 模块职责：模型与只读工具之间的循环图；调用方通过 recursion_limit 限制执行轮次。
from langgraph.graph import StateGraph, START, END
from app.ai.state import OrderAgentState
from app.ai.agent import call_model, execute_tools, route_after_model

#创建builder
builder = StateGraph(OrderAgentState)

builder.add_node("model", call_model)
builder.add_node("tools", execute_tools)

builder.add_edge(START, "model")
builder.add_conditional_edges("model", route_after_model,{"tools": "tools", "end": END})
builder.add_edge("tools", "model")

graph = builder.compile()
