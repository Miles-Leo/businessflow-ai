# 模块职责：订单查询 Repository；只负责数据访问，不决定审核或提交事务。
from sqlalchemy.orm import Session
from app.db.models import Order


def get_order(session: Session, order_id: str) -> Order | None:
    return session.get(Order, order_id)
