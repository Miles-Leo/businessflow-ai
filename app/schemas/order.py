# 模块职责：请求与响应字段契约：order；负责验证和序列化，不执行数据库或外部调用。
from app.schemas.time import BusinessDateTime
from pydantic import BaseModel, ConfigDict


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    order_id: str
    customer_id: str
    created_at: BusinessDateTime
    promised_ship_at: BusinessDateTime
    shipped_at: BusinessDateTime | None
    status: str
