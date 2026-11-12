# 模块职责：任务创建、运行、读取及状态核对；所有者隔离在服务端执行。
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import DemoUser, get_demo_user
from app.db.session import get_db
from app.repositories.tasks import create_task, get_owned_task
from app.schemas.task import AgentTaskCreateRequest, AgentTaskResponse
from app.services.tasks import TaskConflict, TaskNotFound, run_task, refresh_task
from app.repositories.task_events import list_task_events
from app.schemas.task import TaskEventResponse
from app.ai.recovery import recover_task
from app.repositories.tasks import list_owned_tasks
from app.schemas.task_list import AgentTaskListResponse

router = APIRouter(prefix="/agent/tasks", tags=["agent-tasks"])


@router.get("", response_model=AgentTaskListResponse)
def my_tasks(user: Annotated[DemoUser, Depends(get_demo_user)],
             session: Annotated[Session, Depends(get_db)],
             offset: Annotated[int, Query(ge=0)] = 0,
             limit: Annotated[int, Query(ge=1, le=100)] = 20):
    try:
        rows, total = list_owned_tasks(session, user.user_id, offset, limit)
        return AgentTaskListResponse(items=[AgentTaskResponse.model_validate(row) for row in rows],
                                     total=total, offset=offset, limit=limit)
    except SQLAlchemyError:
        raise HTTPException(503, "我的任务暂不可用") from None


@router.post("/{task_id}/recover", response_model=AgentTaskResponse)
def recover_interrupted_task(task_id: str, user: Annotated[DemoUser, Depends(get_demo_user)],
                             session: Annotated[Session, Depends(get_db)]):
    return _task_operation(recover_task, session, task_id, user.user_id)


@router.get("/{task_id}/events", response_model=list[TaskEventResponse])
def read_events(task_id: str, user: Annotated[DemoUser, Depends(get_demo_user)],
                session: Annotated[Session, Depends(get_db)],
                after_id: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=100)] = 50):
    try:
        if get_owned_task(session, task_id, user.user_id) is None:
            raise HTTPException(404, "任务不存在或无权访问")
        return [TaskEventResponse.model_validate(event)
                for event in list_task_events(session, task_id, after_id, limit)]
    except SQLAlchemyError:
        raise HTTPException(503, "任务日志暂不可用") from None


@router.post("/{task_id}/run", response_model=AgentTaskResponse)
def execute_task(task_id: str, user: Annotated[DemoUser, Depends(get_demo_user)],
                 session: Annotated[Session, Depends(get_db)]) -> AgentTaskResponse:
    return _task_operation(run_task, session, task_id, user.user_id)


@router.post("/{task_id}/refresh", response_model=AgentTaskResponse)
def synchronize_task(task_id: str, user: Annotated[DemoUser, Depends(get_demo_user)],
                     session: Annotated[Session, Depends(get_db)]) -> AgentTaskResponse:
    return _task_operation(refresh_task, session, task_id, user.user_id)


def _task_operation(operation, session, task_id, user_id):
    try:
        return operation(session, task_id, user_id)
    except TaskNotFound:
        raise HTTPException(404, "任务不存在或无权访问") from None
    except TaskConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except Exception:
        session.rollback()
        raise HTTPException(503, "任务服务暂不可用，请查询或刷新原任务，请勿重复创建") from None


@router.post("", status_code=201, response_model=AgentTaskResponse)
def register_task(request: AgentTaskCreateRequest, response: Response,
                  user: Annotated[DemoUser, Depends(get_demo_user)],
                  session: Annotated[Session, Depends(get_db)]) -> AgentTaskResponse:
    try:
        with session.begin():
            task = create_task(session, user.user_id, request.user_input)
            result = AgentTaskResponse.model_validate(task)
        # Returned only after the transaction has committed successfully.
        response.headers["Location"] = f"/api/v1/agent/tasks/{result.task_id}"
        return result
    except SQLAlchemyError:
        raise HTTPException(503, "任务保存失败，请勿盲目重复提交") from None


@router.get("/{task_id}", response_model=AgentTaskResponse)
def read_task(task_id: str, user: Annotated[DemoUser, Depends(get_demo_user)],
              session: Annotated[Session, Depends(get_db)]) -> AgentTaskResponse:
    try:
        task = get_owned_task(session, task_id, user.user_id)
        if task is None:
            # Conceal whether another user's task exists.
            raise HTTPException(404, "任务不存在或无权访问")
        return AgentTaskResponse.model_validate(task)
    except SQLAlchemyError:
        raise HTTPException(503, "任务查询暂不可用") from None
