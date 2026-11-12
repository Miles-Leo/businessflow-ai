# 模块职责：政策问答入口；外部依赖失败转换为安全的 HTTP 错误。
from fastapi import APIRouter, HTTPException
from app.schemas.knowledge import PolicyQueryRequest, PolicyQueryResponse

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_policy_answerer():
    # Keep optional retrieval dependencies out of application startup.
    from app.ai.rag import answer_policy_question
    return answer_policy_question


@router.post("/query", response_model=PolicyQueryResponse)
def query_policy(request: PolicyQueryRequest) -> PolicyQueryResponse:
    try:
        answerer = get_policy_answerer()
    except Exception:
        raise HTTPException(503, "政策问答暂不可用，请检查服务端配置") from None
    try:
        result = answerer(request.question, top_k=request.top_k)
        return PolicyQueryResponse.model_validate(result)
    except Exception:
        # Do not return SQL, provider errors, credentials or document payloads.
        raise HTTPException(502, "政策问答执行失败，请稍后重试") from None
