# 模块职责：请求与响应字段契约：approval；负责验证和序列化，不执行数据库或外部调用。
"""HTTP validation models; workflow state remains in app.ai.state."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from app.schemas.time import BusinessDateTime


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]


class ApprovalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_id: str = Field(pattern=r"^BF[0-9]{7}$")


class ApprovalCreateResponse(BaseModel):
    approval_id: str
    approval_status: Literal["pending"]


class ApprovalDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)
    approval_status: Literal["approved", "rejected"]
    reviewer_id: str = Field(min_length=1)
    reviewed_at: BusinessDateTime


class ApprovalPolicySource(BaseModel):
    document_title: str
    section: str
    source: str
    chunk_id: str


class ApprovalProposal(BaseModel):
    order_id: str
    issue_type: Literal["shipping_delay"]
    description: str
    policy_sources: list[ApprovalPolicySource]
    checked_at: BusinessDateTime
    approval_status: Literal["pending", "approved", "rejected"]


class ApprovalDetailResponse(BaseModel):
    approval_id: str
    proposal: ApprovalProposal
    reviewer_id: str | None
    reviewed_at: BusinessDateTime | None


class ApprovalListItem(BaseModel):
    approval_id: str
    order_id: str
    issue_type: Literal["shipping_delay"]
    description: str
    approval_status: Literal["pending", "approved", "rejected"]
    submitted_at: BusinessDateTime | None
    updated_at: BusinessDateTime | None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalListItem]
    total: int
    offset: int
    limit: int
    unavailable_count: int = 0
