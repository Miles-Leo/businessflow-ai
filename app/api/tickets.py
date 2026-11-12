# 模块职责：正式工单查询与状态转换；变更记录和工单状态在同一事务提交。
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.dependencies import DemoUser, require_reviewer
from app.db.session import get_db
from app.repositories.tickets import get_ticket
from app.schemas.ticket import TicketResponse, TicketStatusRequest
from app.db.models import FeishuSync, TicketStatusChange
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.time import business_iso

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.patch("/{ticket_id}/status", response_model=TicketResponse)
def change_status(ticket_id: str, request: TicketStatusRequest,
                  user: Annotated[DemoUser, Depends(require_reviewer)], session: Annotated[Session, Depends(get_db)]):
    with session.begin():
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        ticket = get_ticket(session, ticket_id)
        if ticket is None:
            raise HTTPException(404, "工单不存在")
        sync = session.get(FeishuSync, ticket_id)
        if sync and sync.status in {"in_progress", "unknown"}:
            raise HTTPException(409, "外部同步尚未确认，请先核对结果再修改状态")
        allowed = {"open": {"open", "in_progress", "closed"}, "in_progress": {"in_progress", "closed"}, "closed": {"closed"}}
        if request.status not in allowed.get(ticket.status, set()):
            raise HTTPException(409, "不允许该工单状态转换")
        if ticket.status != request.status:
            session.add(TicketStatusChange(ticket_id=ticket_id, previous_status=ticket.status,
                status=request.status, changed_by=user.user_id, created_at=datetime.now(timezone.utc)))
            ticket.status = request.status
        session.flush()
        result = TicketResponse.model_validate(ticket)
    return result


@router.get("/{ticket_id}/status-history")
def status_history(ticket_id: str, user: Annotated[DemoUser, Depends(require_reviewer)],
                   session: Annotated[Session, Depends(get_db)]):
    if get_ticket(session, ticket_id) is None:
        raise HTTPException(404, "工单不存在")
    rows = session.scalars(select(TicketStatusChange).where(TicketStatusChange.ticket_id == ticket_id)
                           .order_by(TicketStatusChange.change_id).limit(100)).all()
    return [{"change_id": row.change_id, "previous_status": row.previous_status, "status": row.status,
             "changed_by": row.changed_by, "created_at": business_iso(row.created_at)} for row in rows]


@router.get("/{ticket_id}", response_model=TicketResponse)
def read_ticket(ticket_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], session: Annotated[Session, Depends(get_db)]):
    try:
        ticket = get_ticket(session, ticket_id)
        if ticket is None:
            raise HTTPException(404, "工单不存在")
        return TicketResponse.model_validate(ticket)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "工单查询暂不可用") from None
