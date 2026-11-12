# 模块职责：显式建立工单相关表；不创建正式业务工单。
"""Explicit additive table setup; never run automatically on application startup."""
from app.db.models import Ticket, TicketExecution
from app.db.session import engine


if __name__ == "__main__":
    Ticket.__table__.create(engine, checkfirst=True)
    TicketExecution.__table__.create(engine, checkfirst=True)
    print("Ticket tables initialized; existing data preserved.")
