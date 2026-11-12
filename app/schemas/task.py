# 模块职责：请求与响应字段契约：task；负责验证和序列化，不执行数据库或外部调用。
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.time import BusinessDateTime

TaskStatus = Literal["created", "running", "waiting_approval", "rejected", "executing", "completed", "failed"]

from app.schemas.order import OrderResponse
from app.schemas.approval import ApprovalPolicySource, ApprovalProposal


class TaskAssessment(BaseModel):
    order_id: str
    checked_at: BusinessDateTime
    is_overdue_unshipped: bool = Field(strict=True)


class TaskExecutionResult(BaseModel):
    status: Literal["success", "failed"]
    ticket_id: str | None
    attempts: int


class TaskResult(BaseModel):
    query_result: OrderResponse
    assessment: TaskAssessment
    policy_sources: list[ApprovalPolicySource]
    proposal: ApprovalProposal | None
    execution_result: TaskExecutionResult | None = None
    issue: str | None = None


class AgentTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_input: str = Field(min_length=1, max_length=2000)

    @field_validator("user_input")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("任务输入不能为空")
        return value.strip()


class AgentTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    task_id: str
    user_id: str
    user_input: str
    status: TaskStatus
    approval_id: str | None
    ticket_id: str | None
    error: str | None
    answer: str | None = None
    result: TaskResult | None = None
    created_at: BusinessDateTime
    updated_at: BusinessDateTime


class TaskEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: int
    step_name: str | None = None
    task_id: str
    event_type: Literal[
        "task_created", "task_started", "task_completed", "task_failed",
        "review_pending", "review_approved", "review_rejected", "ticket_created", "ticket_failed",
        "tool_completed", "tool_failed", "node_result",
    ]
    status: TaskStatus
    message: str
    created_at: BusinessDateTime
