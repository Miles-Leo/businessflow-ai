# 模块职责：请求与响应字段契约：knowledge；负责验证和序列化，不执行数据库或外部调用。
from pydantic import BaseModel, Field, field_validator


class PolicyQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10, strict=True)

    @field_validator("question")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class PolicySource(BaseModel):
    citation_id: int = Field(ge=1)
    chunk_id: str
    document_title: str
    section: str
    source: str
    score: float = Field(allow_inf_nan=False)


class PolicyQueryResponse(BaseModel):
    answer: str = Field(min_length=1)
    sources: list[PolicySource]

    @field_validator("answer")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("回答不能为空")
        return value
