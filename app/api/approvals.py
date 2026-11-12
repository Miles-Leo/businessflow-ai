# 模块职责：负责人审核和显式执行入口；单进程锁不替代数据库约束。
from contextlib import contextmanager
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import TicketExecution
from app.schemas.ticket import TicketExecuteResponse, TicketExecutionResponse
from app.services.tickets import execute_ticket, TicketExecutionConflict

from app.api.dependencies import DemoUser, require_reviewer, get_demo_user
from app.schemas.approval import ApprovalDecisionRequest, ApprovalDecisionResponse, ApprovalDetailResponse
from app.services.approval import ReviewConflict, ReviewNotFound, submit_review
from app.services.approval import start_review
from app.services.review_runtime import (
    ReviewDatabaseNotInitialized,
    open_review_graph as open_persistent_review_graph,
    review_lock,
)
from app.schemas.approval import ApprovalCreateRequest, ApprovalCreateResponse, ApprovalProposal
from app.schemas.approval import ApprovalListResponse
from app.services.approval_inbox import list_approvals

router = APIRouter(prefix="/approvals", tags=["approvals"])
# Demo runs with one server process. This lock is not cross-process protection.
_review_lock = review_lock


@router.get("", response_model=ApprovalListResponse)
def read_approval_inbox(
    user: Annotated[DemoUser, Depends(require_reviewer)],
    status: Literal["pending", "approved", "rejected", "all"] = "pending",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    query: Annotated[str, Query(max_length=128)] = "",
):
    if not _review_lock.acquire(blocking=False):
        raise HTTPException(409, "审核状态正在更新，请稍后刷新列表")
    try:
        with open_review_graph() as graph:
            return list_approvals(graph, status=status, offset=offset, limit=limit, query=query)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "审核列表暂不可用，请稍后刷新") from None
    finally:
        _review_lock.release()


@router.post("/{approval_id}/execute", response_model=TicketExecuteResponse)
def execute_review(approval_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], session: Annotated[Session, Depends(get_db)]):
    if not _review_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个审核请求正在处理，请稍后重试")
    try:
        with open_review_graph() as graph:
            state = graph.get_state({"configurable": {"thread_id": approval_id}}).values
            if not state:
                raise HTTPException(404, "审核任务不存在")
            return execute_ticket(session, approval_id, state, user.user_id)
    except TicketExecutionConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "工单执行暂不可用，请查询执行记录后再重试") from None
    finally:
        _review_lock.release()


@router.get("/{approval_id}/execution", response_model=TicketExecutionResponse)
def read_execution(approval_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], session: Annotated[Session, Depends(get_db)]):
    try:
        execution = session.get(TicketExecution, approval_id)
        if execution is None:
            raise HTTPException(404, "未找到执行记录")
        return TicketExecutionResponse.model_validate(execution)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "执行记录暂不可用") from None


def prepare_proposal(order_id: str):
    from app.ai.review import prepare_ticket_proposal
    return prepare_ticket_proposal(order_id)


@router.post("", response_model=ApprovalCreateResponse, status_code=201)
def create_review(
    request: ApprovalCreateRequest,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[DemoUser, Depends(get_demo_user)],
) -> ApprovalCreateResponse:
    # Both demo employees and managers may propose; only managers may decide.
    if not _review_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个审核请求正在处理，请稍后重试")
    try:
        with open_review_graph() as graph:
            try:
                proposal = prepare_proposal(request.order_id)
            except ValueError:
                raise HTTPException(409, "未能满足建议生成条件，请检查订单评估和政策依据") from None
            validated = ApprovalProposal.model_validate(proposal)
            if validated.approval_status != "pending" or validated.order_id != request.order_id:
                raise HTTPException(503, "建议结果异常，未启动审核任务")
            from app.services.application_dedup import check_application, DuplicateApplication
            try:
                check_application(graph, session, proposal)
            except DuplicateApplication as exc:
                raise HTTPException(409, str(exc)) from None
            result = start_review(graph, proposal)
            return ApprovalCreateResponse.model_validate(result)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "创建审核任务失败，请勿盲目重复提交") from None
    finally:
        _review_lock.release()


@contextmanager
def open_review_graph():
    # HTTP 层负责将公共运行模块的异常转换为接口响应。
    try:
        with open_persistent_review_graph() as graph:
            yield graph
    except ReviewDatabaseNotInitialized as exc:
        raise HTTPException(503, str(exc)) from None


@router.get("/{approval_id}", response_model=ApprovalDetailResponse)
def read_review(
    approval_id: str,
    user: Annotated[DemoUser, Depends(require_reviewer)],
) -> ApprovalDetailResponse:
    try:
        with open_review_graph() as graph:
            snapshot = graph.get_state({"configurable": {"thread_id": approval_id}})
            if not snapshot.values:
                raise HTTPException(404, "审核任务不存在")
            return ApprovalDetailResponse(
                approval_id=approval_id,
                proposal=snapshot.values["proposal"],
                reviewer_id=snapshot.values["reviewer_id"],
                reviewed_at=snapshot.values["reviewed_at"],
            )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "审核详情暂不可用，请稍后重试") from None


@router.post("/{approval_id}/decision", response_model=ApprovalDecisionResponse)
def decide_review(
    approval_id: str,
    request: ApprovalDecisionRequest,
    user: Annotated[DemoUser, Depends(require_reviewer)],
) -> ApprovalDecisionResponse:
    if not _review_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个审核请求正在处理，请稍后重试")
    try:
        with open_review_graph() as graph:
            result = submit_review(graph, approval_id, request.decision, user.user_id)
            return ApprovalDecisionResponse(
                approval_id=approval_id,
                approval_status=result["proposal"]["approval_status"],
                reviewer_id=result["reviewer_id"],
                reviewed_at=result["reviewed_at"],
            )
    except ReviewNotFound:
        raise HTTPException(404, "审核任务不存在") from None
    except ReviewConflict:
        raise HTTPException(409, "审核任务已完成或当前不可审核") from None
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "审核暂不可用，请查询任务状态后再重试") from None
    finally:
        _review_lock.release()
