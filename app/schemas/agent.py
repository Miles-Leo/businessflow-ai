# 模块职责：请求与响应字段契约：agent；负责验证和序列化，不执行数据库或外部调用。
from pydantic import BaseModel, Field, field_validator


class AgentQueryRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=2000)

    @field_validator("user_input")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("输入不能为空")
        return value.strip()


class AgentQueryResponse(BaseModel):
    answer: str
