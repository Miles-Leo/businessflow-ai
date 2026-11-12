# 模块职责：请求与响应字段契约：task_list；负责验证和序列化，不执行数据库或外部调用。
from pydantic import BaseModel
from app.schemas.task import AgentTaskResponse


class AgentTaskListResponse(BaseModel):
    items: list[AgentTaskResponse]
    total: int
    offset: int
    limit: int
