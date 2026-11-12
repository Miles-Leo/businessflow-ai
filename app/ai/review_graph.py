# 模块职责：审核演示图；用于理解中断与恢复，持久化运行入口见 services/review_runtime.py。
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from app.ai.state import TicketReviewState
from app.ai.review import wait_for_review

builder = StateGraph(TicketReviewState)

builder.add_node("review", wait_for_review)

builder.add_edge(START, "review")
builder.add_edge("review", END)

review_graph = builder.compile(checkpointer=InMemorySaver())
