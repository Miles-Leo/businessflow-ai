# 模块职责：请求与响应字段契约：feishu_sync；负责验证和序列化，不执行数据库或外部调用。
from app.schemas.time import BusinessDateTime
from typing import Literal
from pydantic import BaseModel, ConfigDict


class FeishuSyncResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ticket_id: str
    request_id: str
    status: Literal["in_progress", "success", "failed", "unknown"]
    record_id: str | None
    attempts: int
    requested_by: str
    error: str | None
    updated_at: BusinessDateTime
