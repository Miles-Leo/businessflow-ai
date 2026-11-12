# 模块职责：客户查询 Repository；数据范围由上层权限规则限制。
from app.db.models import Customer


def get_customer(session, customer_id: str):
    return session.get(Customer, customer_id)
