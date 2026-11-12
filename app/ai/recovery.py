# 模块职责：单进程任务恢复；核对已保存事实，不自动重放结果未知的业务写入。
"""Explicit recovery for the single-process demo, without replaying business writes."""
from contextlib import contextmanager
from threading import Lock

_guard = Lock()
_active_tasks = set()


@contextmanager
def task_execution_guard(task_id: str):
    from app.services.tasks import TaskConflict
    with _guard:
        if task_id in _active_tasks:
            raise TaskConflict("该任务仍在当前进程执行，请稍后再试")
        _active_tasks.add(task_id)
    try:
        yield
    finally:
        with _guard:
            _active_tasks.discard(task_id)


def recover_task(session, task_id: str, user_id: str):
    from datetime import datetime, timezone
    from app.services.tasks import refresh_task, owned_task
    from app.schemas.task import AgentTaskResponse
    from app.repositories.task_events import append_task_event

    with session.begin():
        owned_task(session, task_id, user_id)
    with task_execution_guard(task_id):
        result = refresh_task(session, task_id, user_id)
        if result.status != "running" or result.approval_id:
            return result
        # No checkpoint exists: do not replay a model/tool call with uncertain history.
        with session.begin():
            task = owned_task(session, task_id, user_id)
            task.status = "failed"
            task.error = "执行已中断且无审核检查点，未自动重跑；核对结果后可创建新任务"
            task.answer = None
            task.updated_at = datetime.now(timezone.utc)
            append_task_event(session, task_id, "recovery_failed", "task_failed", "failed")
            session.flush()
            return AgentTaskResponse.model_validate(task)
