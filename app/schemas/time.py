# 模块职责：请求与响应字段契约：time；负责验证和序列化，不执行数据库或外部调用。
from typing import Annotated
from pydantic import AwareDatetime, PlainSerializer
from app.core.time import business_iso

# Validation/comparison retain aware datetime objects; JSON carries explicit +08:00.
BusinessDateTime = Annotated[AwareDatetime, PlainSerializer(business_iso, return_type=str, when_used="json")]
