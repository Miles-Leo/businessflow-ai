# 模块职责：请求与响应字段契约：customer；负责验证和序列化，不执行数据库或外部调用。
from pydantic import BaseModel, ConfigDict


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_id: str
    name: str
    contact: str
