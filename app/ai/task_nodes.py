# 模块职责：任务节点适配层；组织已有服务，统一输出状态增量与安全错误。
from typing import Literal
from pydantic import BaseModel, Field
from app.ai.state import TaskWorkflowState
from app.ai.model import create_chat_model
from app.ai.prompts import TASK_PARSER_SYSTEM_PROMPT



class TaskIntent(BaseModel):
    intent: Literal["query", "create_proposal", "sync_ticket", "unknown"]
    order_id: str | None = Field(default=None, pattern=r"^BF[0-9]{7}$")
    ticket_id: str | None = Field(default=None, pattern=r"^TK-[A-Za-z0-9-]+$", max_length=64)


def parse_task(state: TaskWorkflowState) -> dict[str, object]:



    try:
        return _parse_task(state)
    except Exception:
        return {"intent": "unknown", "order_id": None, "error": "任务解析暂时不可用，请稍后重试"}


# 任务解析节点
def _parse_task(state: TaskWorkflowState) -> dict[str, object]:
    parser = create_chat_model().with_structured_output(TaskIntent)
    message = [
        {"role": "system", "content": TASK_PARSER_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户提问:{state['user_input']}"},
    ]
    response = parser.invoke(
        message
    )
    intent = response.intent
    order_id = response.order_id
    error = None
    update = {
        "intent": intent,
        "order_id": order_id,
        "error": error,
    }
    if response.intent == "sync_ticket":
        update["ticket_id"] = response.ticket_id
    return update


#路由函数
def route_after_parse(
    state: TaskWorkflowState,
) -> Literal["query", "create_proposal", "sync_ticket", "unsupported", "missing_order_id"]:




    if state["intent"] == "sync_ticket":
        return "sync_ticket"
    if state["intent"] == "create_proposal" and state["order_id"] is None:
        return "missing_order_id"
    elif state["intent"] == "unknown":
        return "unsupported"
    elif state["intent"] == "query":
        return "query"
    elif state["intent"] == "create_proposal":
        return "create_proposal"
    else:
        raise ValueError(f"Unknown intent: {state['intent']}")

# 处理不支持的意图
def handle_unsupported(state: TaskWorkflowState) -> dict[str, object]:

    return {"error": "当前不支持该操作，不能绕过审核"}




# 处理缺少订单号的意图
def handle_missing_order_id(state: TaskWorkflowState) -> dict[str, object]:

    return {"error": "生成待审核建议需要提供订单编号"}



#查询节点
# 维护约束：调用只读 Agent 并检查最终消息完整性；工具故障不能被自然语言成功回复掩盖。
def run_query(state: TaskWorkflowState) -> dict[str, object]:
    import json
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    from langgraph.errors import GraphRecursionError





    message = HumanMessage(content=state["user_input"])

    # 导入时也可能因模型配置缺失而失败，因此一并捕获。
    try:
        from app.ai.agent_graph import graph

        response = graph.invoke(
            {"messages": [message]},
            config={"recursion_limit": 10},
        )
    except GraphRecursionError:
        return {"answer": None, "error": "查询超过执行步数限制，请简化请求"}
    except Exception:
        return {"answer": None, "error": "查询暂时不可用，请稍后重试"}

    messages = response.get("messages", [])
    for item in messages:
        if isinstance(item, ToolMessage):
            try:
                payload = json.loads(item.content) if isinstance(item.content, str) else None
            except (TypeError, ValueError):
                payload = None
            if not isinstance(payload, dict) or payload.get("status") == "failed":
                return {"answer": None, "error": "部分业务工具查询失败，当前任务未能完整完成，请稍后重试"}
    last = messages[-1] if messages else None


    # 只接受完整的最终 AI 文本，不能将仍需工具调用的中间消息作为业务结果。
    if not isinstance(last, AIMessage):
        return {"answer": None, "error": "查询未返回完整文本回复"}
    elif last.tool_calls:
        return {"answer": None, "error": "查询未返回完整文本回复"}
    elif not isinstance(last.content, str) or not last.content.strip():
        return {"answer": None, "error": "查询未返回完整文本回复"}

    answer = last.content
    error = None
    return {"answer": answer, "error": error}


#生成建议节点
# 维护约束：使用同一次查询形成结构化结果；不满足条件时不启动审核。
def generate_proposal(state: TaskWorkflowState) -> dict[str, object]:
    order_id = state["order_id"]
    if not order_id:
        return {
            "proposal": None,
            "error": "生成待审核建议需要提供订单编号",
        }

    try:
        from app.ai.review import prepare_ticket_proposal_result

        proposal, answer, result = prepare_ticket_proposal_result(order_id, structured=True)
    except ValueError:
        return {
            "proposal": None,
            "error": "未能满足建议生成条件，请检查订单评估和政策依据",
        }

    except Exception:
        return {
            "proposal": None,
            "error": "建议生成暂时不可用，请稍后重试",
        }

    return {"proposal": proposal, "answer": answer, "result": result, "error": result.get("issue") if result else None}


# 维护约束：只启动或复用审核检查点，不能批准建议或创建正式工单。
def begin_review(state: TaskWorkflowState) -> dict[str, object]:
    """Persist a review under the task UUID; never approve or execute it here."""
    from app.schemas.approval import ApprovalProposal
    from app.services.approval import start_review
    from app.services.review_runtime import open_review_graph, review_lock
    from app.services.task_answers import with_progress

    if state.get("approval_id"):
        return {"approval_id": state["approval_id"], "error": None,
                "answer": with_progress(None if state.get("result") else state.get("answer"), "建议已提交，等待负责人审核；尚未创建正式工单。")}
    try:
        proposal = ApprovalProposal.model_validate(state.get("proposal"))
        if proposal.approval_status != "pending" or proposal.order_id != state.get("order_id"):
            raise ValueError("Invalid proposal")
    except ValueError:
        return {"approval_id": None, "answer": None, "error": "缺少有效的待审核建议，未启动审核"}

    if not review_lock.acquire(blocking=False):
        return {"approval_id": None, "answer": None, "error": "另一个审核请求正在处理，请稍后查询任务状态"}
    try:
        approval_id = state["task_id"]
        with open_review_graph() as graph:
            config = {"configurable": {"thread_id": approval_id}}
            saved = graph.get_state(config).values
            if saved:
                previous = ApprovalProposal.model_validate(saved["proposal"])
                if previous.order_id != proposal.order_id:
                    raise ValueError("Review order mismatch")
                # Never invoke START again over an existing checkpoint.
            else:
                from app.db.session import SessionLocal
                from app.services.application_dedup import check_application
                with SessionLocal() as session:
                    check_application(graph, session, proposal.model_dump(mode="json"), own_approval_id=approval_id)
                start_review(graph, proposal.model_dump(mode="json"), approval_id=approval_id)
        return {"approval_id": approval_id, "error": None,
                "answer": with_progress(None if state.get("result") else state.get("answer"), "建议已提交，等待负责人审核；尚未创建正式工单。")}
    except ValueError as exc:
        from app.services.application_dedup import DuplicateApplication
        return {"approval_id": None, "answer": None, "error": str(exc) if isinstance(exc, DuplicateApplication) else "启动审核校验失败，未创建申请"}
    except Exception:
        return {"approval_id": None, "answer": None,
                "error": "启动审核未能确认，请刷新任务状态，请勿重复创建任务"}
    finally:
        review_lock.release()


def sync_formal_ticket(state: TaskWorkflowState) -> dict[str, object]:
    """Only the server-selected demo manager can sync an already executed ticket."""
    if state.get("user_id") != "reviewer-demo-001":
        return {"ticket_id": None, "answer": None, "error": "只有负责人可以同步正式工单"}
    ticket_id = state.get("ticket_id")
    if not ticket_id:
        return {"ticket_id": None, "answer": None, "error": "请提供正式工单编号 TK-..."}
    from app.db.session import SessionLocal
    from app.services.feishu_sync import sync_ticket
    try:
        result = sync_ticket(SessionLocal, ticket_id, state["user_id"])
        if result.status != "success":
            raise ValueError("Unconfirmed sync")
        return {"ticket_id": ticket_id, "answer": f"工单已同步到飞书，记录编号：{result.record_id}", "error": None}
    except Exception:
        return {"ticket_id": None, "answer": None, "error": "飞书同步未确认，请查询工单同步记录，勿盲目重发"}
