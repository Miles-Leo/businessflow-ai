# 模块职责：基础订单查询图：正则提取编号后查询；与自然语言任务主图分开。

from langgraph.graph import StateGraph
from langgraph.constants import START, END
from typing import Literal

from app.ai.nodes import extract_order_id, query_order
from app.ai.state import OrderQueryState


def route_after_extract(
    state: OrderQueryState,
) -> Literal["query", "end"]:

    return "query" if state["order_id"] is not None else "end"

builder = StateGraph(OrderQueryState)

builder.add_node("extract_order_id", extract_order_id)
builder.add_node("query_order", query_order)

builder.add_edge(START, "extract_order_id")
builder.add_conditional_edges("extract_order_id", route_after_extract,{"query": "query_order", "end": END},)
builder.add_edge("query_order", END)

condition_graph=builder.compile()
