# 模块职责：本地演示数据访问范围；不等同于生产租户权限模型。
"""Explicit local demo scope; not tenant authentication."""
DEMO_CUSTOMER_ID = "CUST-DEMO-001"


def can_read_customer(customer_id: str, role: str = "employee") -> bool:
    return role == "manager" or customer_id == DEMO_CUSTOMER_ID
