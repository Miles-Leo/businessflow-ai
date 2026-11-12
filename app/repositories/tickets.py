# 模块职责：工单查询 Repository；支持按审核编号复用已创建工单。
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Ticket


def get_ticket(session: Session, ticket_id: str) -> Ticket | None:
    return session.get(Ticket, ticket_id)


def get_ticket_by_approval(session: Session, approval_id: str) -> Ticket | None:
    return session.scalar(select(Ticket).where(Ticket.approval_id == approval_id))
