# 模块职责：任务数据访问与所有者过滤；新增记录只 flush，提交由上层负责。
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db.models import AgentTask
from app.repositories.task_events import append_task_event


def create_task(session: Session, user_id: str, user_input: str) -> AgentTask:
    """Insert and flush; transaction commit belongs to the API/service caller."""
    now = datetime.now(timezone.utc)
    task = AgentTask(
        task_id=str(uuid4()), user_id=user_id, user_input=user_input,
        status="created", approval_id=None, ticket_id=None, error=None,
        created_at=now, updated_at=now,
    )
    session.add(task)
    session.flush()
    append_task_event(session, task.task_id, "created", "task_created", "created")
    return task


def get_owned_task(session: Session, task_id: str, user_id: str) -> AgentTask | None:
    return session.scalar(select(AgentTask).where(
        AgentTask.task_id == task_id, AgentTask.user_id == user_id,
    ))


def list_owned_tasks(session: Session, user_id: str, offset: int, limit: int):
    query = select(AgentTask).where(AgentTask.user_id == user_id)
    total = session.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.user_id == user_id))
    tasks = session.scalars(query.order_by(AgentTask.created_at.desc(), AgentTask.task_id).offset(offset).limit(limit)).all()
    return tasks, total
