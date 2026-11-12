# 模块职责：自然语言任务主图；解析意图后路由查询、建议或受控同步分支。
"""Natural-language entry graph; approval and ticket execution remain controlled APIs."""
from langgraph.graph import END, START, StateGraph

from app.ai.state import TaskWorkflowState
from app.ai import task_nodes
from app.services.trace import record_step


def traced(name, function):
    def run(state):
        try:
            result = function(state)
            record_step(name, bool(result.get("error")))
            return result
        except Exception:
            record_step(name, True)
            raise
    return run


def route_parsed(state: TaskWorkflowState):
    if state.get("error"):
        return "failed"
    return task_nodes.route_after_parse(state)


def route_proposal(state: TaskWorkflowState):
    return "failed" if state.get("error") or not state.get("proposal") else "review"


def build_task_graph():
    builder = StateGraph(TaskWorkflowState)
    for name, function in {
        "parse": task_nodes.parse_task, "query": task_nodes.run_query,
        "proposal": task_nodes.generate_proposal, "review": task_nodes.begin_review,
        "unsupported": task_nodes.handle_unsupported, "missing_order_id": task_nodes.handle_missing_order_id,
        "sync_ticket": task_nodes.sync_formal_ticket,
    }.items():
        builder.add_node(name, traced(name, function))
    builder.add_edge(START, "parse")
    builder.add_conditional_edges("parse", route_parsed, {
        "query": "query", "create_proposal": "proposal", "unsupported": "unsupported",
        "missing_order_id": "missing_order_id", "failed": END,
        "sync_ticket": "sync_ticket",
    })
    builder.add_conditional_edges("proposal", route_proposal, {"review": "review", "failed": END})
    for node in ("query", "review", "unsupported", "missing_order_id", "sync_ticket"):
        builder.add_edge(node, END)
    return builder.compile()
