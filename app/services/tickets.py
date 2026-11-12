# 模块职责：正式工单执行边界；重新校验订单，用事务和唯一约束防止重复创建。
"""SQLite transaction is the idempotency boundary; never trust a client proposal."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session
from app.db.models import Order, Ticket, TicketExecution
from app.repositories.tickets import get_ticket_by_approval
from app.schemas.approval import ApprovalDetailResponse
from app.schemas.ticket import TicketExecuteResponse, TicketResponse
from app.services.shipping import assess_order_shipping


class TicketExecutionConflict(ValueError):
    pass


# 维护约束：信任服务端检查点而非客户端建议；审批记录完整且当前订单合规才允许写入。
def execute_ticket(session: Session, approval_id: str, saved_state: dict, executed_by: str) -> TicketExecuteResponse:
    # The caller loads this state from the server checkpoint, not the request body.
    review = ApprovalDetailResponse.model_validate({"approval_id": approval_id, **saved_state})
    if review.proposal.approval_status != "approved" or not review.reviewer_id or review.reviewed_at is None:
        raise TicketExecutionConflict("只有审核记录完整的已批准建议可以执行")
    if not executed_by.strip():
        raise TicketExecutionConflict("执行人不能为空")
    failure = None
    response = None
    with session.begin():
        # Serializes check+insert across connections/processes for local SQLite.
        # Do not replace with only a Python lock: tickets.approval_id is also UNIQUE.
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        existing = get_ticket_by_approval(session, approval_id)
        if existing is not None:
            if existing.order_id != review.proposal.order_id:
                raise TicketExecutionConflict("审核任务与已有工单不一致")
            response = TicketExecuteResponse(ticket=TicketResponse.model_validate(existing), reused=True)
        else:
            from sqlalchemy import select
            duplicate = session.scalar(select(Ticket).where(Ticket.order_id == review.proposal.order_id, Ticket.issue_type == review.proposal.issue_type, Ticket.status != "closed"))
            if duplicate:
                raise TicketExecutionConflict("该订单已有未关闭的同类工单，禁止通过另一审核重复创建")
            now = datetime.now(timezone.utc)
            execution = session.get(TicketExecution, approval_id)
            if execution is None:
                # A valid provisional value is required during ORM autoflush;
                # it remains invisible outside this transaction until commit.
                execution = TicketExecution(approval_id=approval_id, attempts=0, status="failed")
                session.add(execution)
            execution.attempts += 1
            execution.updated_at = now
            order = session.get(Order, review.proposal.order_id)
            if order is None:
                failure = "订单不存在，未创建工单"
            else:
                try:
                    current = assess_order_shipping({
                        "order_id": order.order_id, "status": order.status,
                        "promised_ship_at": order.promised_ship_at.isoformat(),
                        "shipped_at": order.shipped_at.isoformat() if order.shipped_at else None,
                    }, now)
                    if not current["is_overdue_unshipped"]:
                        failure = "订单已不属于超期未发货，请重新生成建议"
                except ValueError:
                    failure = "当前订单数据存在冲突，未创建工单"
            codes = {p.section.split("：", 1)[0] for p in review.proposal.policy_sources}
            if not {"AS-04", "AS-05"}.issubset(codes):
                failure = "缺少必要政策依据，未创建工单"
            if failure:
                execution.status = "failed"
                execution.ticket_id = None
                execution.error = failure
            else:
                ticket = Ticket(
                    ticket_id="TK-" + uuid4().hex, approval_id=approval_id,
                    order_id=review.proposal.order_id, issue_type=review.proposal.issue_type,
                    description=review.proposal.description, status="open", created_at=now,
                    reviewer_id=review.reviewer_id, reviewed_at=review.reviewed_at,
                    executed_by=executed_by.strip(),
                    policy_sources=[p.model_dump() for p in review.proposal.policy_sources],
                )
                session.add(ticket)
                session.flush()
                execution.status = "success"
                execution.ticket_id = ticket.ticket_id
                execution.error = None
                response = TicketExecuteResponse(ticket=TicketResponse.model_validate(ticket), reused=False)
    # Failure record is committed; unexpected DB errors instead roll back everything.
    if failure:
        raise TicketExecutionConflict(failure)
    return response
