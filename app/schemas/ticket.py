# 模块职责：请求与响应字段契约：ticket；负责验证和序列化，不执行数据库或外部调用。
from app.schemas.time import BusinessDateTime
from typing import Literal
from pydantic import BaseModel, ConfigDict
from app.schemas.approval import ApprovalPolicySource


class TicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ticket_id: str
    approval_id: str
    order_id: str
    issue_type: Literal["shipping_delay"]
    description: str
    status: Literal["open", "in_progress", "closed"]
    created_at: BusinessDateTime
    reviewer_id: str
    reviewed_at: BusinessDateTime
    executed_by: str
    policy_sources: list[ApprovalPolicySource]


class TicketExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    approval_id: str
    status: Literal["success", "failed"]
    ticket_id: str | None
    attempts: int
    error: str | None
    updated_at: BusinessDateTime


class TicketExecuteResponse(BaseModel):
    ticket: TicketResponse
    reused: bool


class TicketStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "closed"]
