# 模块职责：任务事件去重写入与分页；只保存安全摘要，不保存原始工具数据。
"""Fixed summaries only; never store prompts, tool payloads or exception text."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.db.models import TaskEvent


EVENT_MESSAGES = {
    "task_created": "任务已登记，尚未执行。",
    "task_started": "任务已开始执行。",
    "task_completed": "任务已完成，结果已保存。",
    "task_failed": "任务执行失败，请查看任务状态中的安全错误提示。",
    "review_pending": "已确认存在待审核建议，尚未创建正式工单。",
    "review_approved": "刷新时确认建议已批准，正式工单仍需核对执行记录。",
    "review_rejected": "刷新时确认建议已拒绝，未创建正式工单。",
    "ticket_created": "刷新时确认正式工单已创建成功。",
    "ticket_failed": "刷新时确认正式工单执行失败，请负责人核对执行记录。",
    "tool_completed": "业务工具返回成功，原始内容未写入日志。",
    "tool_failed": "业务工具未成功返回结果，请核对任务说明。",
    "node_result": "工作流节点已结束，原始内容未写入日志。",
}


def append_task_event(session, task_id: str, event_key: str, event_type: str, status: str, *, step_name: str | None = None):
    """Caller owns the transaction; an observed fact is inserted at most once."""
    session.execute(insert(TaskEvent).values(
        task_id=task_id, event_key=event_key, event_type=event_type, status=status,
        message=EVENT_MESSAGES[event_type], created_at=datetime.now(timezone.utc), step_name=step_name,
    ).on_conflict_do_nothing(index_elements=["task_id", "event_key"]))


def list_task_events(session, task_id: str, after_id: int, limit: int):
    return session.scalars(select(TaskEvent).where(
        TaskEvent.task_id == task_id, TaskEvent.event_id > after_id,
    ).order_by(TaskEvent.event_id).limit(limit)).all()
