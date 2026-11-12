# 模块职责：兼容的只读 Agent HTTP 入口；不直接提供业务写工具。
from fastapi import APIRouter, HTTPException, Depends
from typing import Annotated
from app.api.dependencies import DemoUser, get_demo_user
from app.schemas.agent import AgentQueryRequest, AgentQueryResponse

router = APIRouter(prefix="/agent", tags=["agent"])


def get_agent_graph():
    # Lazy import keeps health/docs available without model credentials.
    from app.ai.agent_graph import graph
    return graph


@router.post("/query", response_model=AgentQueryResponse)
def query_agent(request: AgentQueryRequest, user: Annotated[DemoUser, Depends(get_demo_user)]) -> AgentQueryResponse:
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.errors import GraphRecursionError

    try:
        graph = get_agent_graph()
    except Exception:
        raise HTTPException(503, "Agent 暂不可用，请检查服务端配置") from None

    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=request.user_input)]},
            config={"recursion_limit": 10},
        )
    except GraphRecursionError:
        raise HTTPException(503, "任务超过执行步数限制，请简化请求") from None
    except Exception:
        # Do not expose provider errors, credentials or business payloads.
        raise HTTPException(502, "Agent 执行失败，请稍后重试") from None

    messages = result.get("messages", [])
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage) or last.tool_calls or not isinstance(last.content, str) or not last.content.strip():
        raise HTTPException(502, "Agent 未返回完整文本回复")
    return AgentQueryResponse(answer=last.content)
