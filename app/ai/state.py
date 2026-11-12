# 模块职责：LangGraph 状态契约；区分消息累加、业务事实、建议与流程状态。

from typing import Literal, TypedDict
from typing import Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

# 订单查询状态
class OrderQueryState(TypedDict):
    user_input: str
    order_id: str | None
    order: dict[str, object] | None
    execution_status: Literal["pending", "running", "success", "not_found", "failed"]
    error: str | None

# 订单查询智能体状态
class OrderAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

# 工单建议状态
class TicketProposal(TypedDict):

    order_id: str
    issue_type: Literal["shipping_delay"]
    description: str
    policy_sources: list[dict[str, str]]
    checked_at: str
    approval_status: Literal["pending", "approved", "rejected"]

# 审核工作流state
class TicketReviewState(TypedDict):

    proposal: TicketProposal
    reviewer_id: str | None
    reviewed_at: str | None

# 任务工作流状态
class TaskWorkflowState(TypedDict):
    result: dict | None
    task_id: str
    user_input: str
    intent: Literal["query", "create_proposal", "sync_ticket", "unknown"]
    order_id: str | None
    approval_id: str | None
    error: str | None
    answer: str | None
    proposal: TicketProposal | None
    ticket_id: str | None
    user_id: str
