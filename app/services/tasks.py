# 模块职责：任务编排与状态投影；模型调用期间不持有数据库写事务。
"""Persist task lifecycle in short transactions, without holding DB locks during model calls."""
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db.models import AgentTask, TicketExecution
from app.repositories.tasks import get_owned_task
from app.repositories.task_events import append_task_event
from app.schemas.approval import ApprovalDetailResponse
from app.schemas.task import AgentTaskResponse
from app.services.trace import capture_trace
from app.services.task_answers import with_progress


class TaskNotFound(ValueError):
    pass


class TaskConflict(ValueError):
    pass


def get_task_graph():
    from app.ai.task_graph import build_task_graph
    return build_task_graph()


def owned_task(session, task_id, user_id):
    task = get_owned_task(session, task_id, user_id)
    if task is None:
        raise TaskNotFound("任务不存在或无权访问")
    return task


def run_task(session: Session, task_id: str, user_id: str) -> AgentTaskResponse:
    from app.ai.recovery import task_execution_guard
    with session.begin():
        owned_task(session, task_id, user_id)
    with task_execution_guard(task_id):
        return _run_task(session, task_id, user_id)


# 维护约束：先原子领取任务，再执行外部调用，最后用短事务保存结果与轨迹。
def _run_task(session: Session, task_id: str, user_id: str) -> AgentTaskResponse:
    with session.begin():
        # Atomic compare-and-set prevents concurrent requests/processes executing twice.
        claimed = session.execute(update(AgentTask).where(
            AgentTask.task_id == task_id, AgentTask.user_id == user_id,
            AgentTask.status == "created",
        ).values(status="running", updated_at=datetime.now(timezone.utc)))
        task = owned_task(session, task_id, user_id)
        if claimed.rowcount != 1:
            if task.status == "running":
                raise TaskConflict("任务正在执行或上次执行结果未确认，请刷新状态，不要重复启动")
            return AgentTaskResponse.model_validate(task)
        user_input = task.user_input
        append_task_event(session, task_id, "started", "task_started", "running")

    initial = {
        "task_id": task_id, "user_input": user_input, "intent": "unknown",
        "order_id": None, "approval_id": None, "error": None,
        "answer": None, "proposal": None,
        "ticket_id": None, "user_id": user_id,
    }
    result = {}
    try:
        with capture_trace() as trace:
            result = get_task_graph().invoke(initial, config={"recursion_limit": 12})
        error = result.get("error")
        answer = result.get("answer")
        approval_id = result.get("approval_id")
        if error:
            # Nodes return fixed safe errors. Limit database size as well.
            error = str(error)[:300]
            status = "failed"
            answer = None
        elif approval_id:
            if approval_id != task_id:
                raise ValueError("Unexpected approval id")
            status = "waiting_approval"
        elif isinstance(answer, str) and answer.strip():
            status = "completed"
        else:
            raise ValueError("Incomplete workflow result")
    except Exception:
        status, answer, approval_id = "failed", None, None
        error = "任务执行未能确认，请刷新状态，请勿盲目重复提交"

    with session.begin():
        task = owned_task(session, task_id, user_id)
        # A concurrent refresh may already have recovered the checkpoint/result.
        if task.status == "running":
            for index, (name, failed, tool) in enumerate(trace):
                event_type = ("tool_failed" if failed else "tool_completed") if tool else "node_result"
                append_task_event(session, task_id, f"step:{index}:{name}", event_type, "failed" if failed else "completed", step_name=name)
            task.status, task.answer, task.error = status, answer, error
            task.approval_id = approval_id
            from app.schemas.task import TaskResult
            structured_result = result.get("result")
            task.result = TaskResult.model_validate(structured_result).model_dump(mode="json") if structured_result else None
            if not error and result.get("ticket_id"):
                task.ticket_id = result["ticket_id"]
            task.updated_at = datetime.now(timezone.utc)
            event_type = {"completed": "task_completed", "failed": "task_failed",
                          "waiting_approval": "review_pending"}[status]
            key = "review:pending" if status == "waiting_approval" else "run_finished"
            append_task_event(session, task_id, key, event_type, status)
            session.flush()
        return AgentTaskResponse.model_validate(task)


# 维护约束：只投影已有审核与执行记录；禁止在刷新路径重放模型或执行业务写入。
def refresh_task(session: Session, task_id: str, user_id: str) -> AgentTaskResponse:
    """Project existing review/execution facts; never resume or execute a write tool."""
    from app.services.review_runtime import open_review_graph, review_lock

    with session.begin():
        task = owned_task(session, task_id, user_id)
        original = AgentTaskResponse.model_validate(task)
    if original.approval_id is None and original.status not in {"running", "failed"}:
        return original
    approval_id = original.approval_id or task_id
    if not review_lock.acquire(blocking=False):
        raise TaskConflict("审核请求正在处理，请稍后刷新")
    try:
        with open_review_graph() as graph:
            saved = graph.get_state({"configurable": {"thread_id": approval_id}}).values
        if not saved:
            if original.approval_id:
                raise TaskConflict("关联审核记录不可用，请核对检查点数据库")
            return original
        review = ApprovalDetailResponse.model_validate({"approval_id": approval_id, **saved})
        decision = review.proposal.approval_status
        with session.begin():
            execution = session.get(TicketExecution, approval_id)
            task = owned_task(session, task_id, user_id)
            # Never replace a completed ticket with an older pending snapshot.
            if task.status == "completed" and task.ticket_id:
                return AgentTaskResponse.model_validate(task)
            task.approval_id = approval_id
            task.error = None
            task.ticket_id = None
            previous_answer = task.answer
            if task.result:
                task.result = {**task.result, "execution_result": {"status": execution.status, "ticket_id": execution.ticket_id, "attempts": execution.attempts} if execution else None}
            if decision == "rejected":
                task.status = "rejected"
                task.answer = "负责人已拒绝建议，未创建正式工单。"
            elif decision == "approved":
                if not review.reviewer_id or review.reviewed_at is None:
                    raise TaskConflict("审核记录不完整，无法确认执行状态")
                if execution and execution.status == "success" and execution.ticket_id:
                    from app.db.models import Ticket
                    ticket = session.get(Ticket, execution.ticket_id)
                    if ticket is None or ticket.approval_id != approval_id:
                        raise TaskConflict("工单与执行记录不一致，请核对业务数据")
                    task.status, task.ticket_id = "completed", ticket.ticket_id
                    task.answer = f"正式工单已创建，编号：{ticket.ticket_id}。"
                elif execution and execution.status == "failed":
                    task.status = "failed"
                    task.error = "正式工单执行失败，请由负责人查询执行记录"
                    task.answer = None
                else:
                    # 'executing' is the approved execution stage, not proof of a created ticket.
                    task.status = "executing"
                    task.answer = "建议已批准，等待负责人通过受控执行接口创建正式工单。"
            else:
                task.status = "waiting_approval"
                task.answer = "建议已提交，等待负责人审核；尚未创建正式工单。"
            if task.answer:
                task.answer = with_progress(None if task.result else previous_answer, task.answer)
            task.updated_at = datetime.now(timezone.utc)
            decision_status = {"pending": "waiting_approval", "approved": "executing", "rejected": "rejected"}[decision]
            decision_type = {"pending": "review_pending", "approved": "review_approved", "rejected": "review_rejected"}[decision]
            append_task_event(session, task_id, f"review:{decision}", decision_type, decision_status)
            if decision == "approved" and execution:
                event_type = "ticket_created" if task.ticket_id else "ticket_failed"
                append_task_event(session, task_id, f"execution:{execution.attempts}:{execution.status}", event_type, task.status)
            session.flush()
            return AgentTaskResponse.model_validate(task)
    finally:
        review_lock.release()
