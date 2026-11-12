# 模块职责：显式准备虚构演示数据；不作为应用启动钩子。
"""Explicit demo initialization: python -m app.db.seed."""
from datetime import datetime, timezone
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from app.db.models import Customer, Order
from app.db.session import Base, engine


def initialize_demo_data(target_engine: Engine) -> None:
    # create_all creates missing tables; it does not migrate existing schemas.
    Base.metadata.create_all(target_engine)
    with Session(target_engine) as session, session.begin():
        if session.get(Customer, "CUST-DEMO-001") is None:
            session.add(Customer(customer_id="CUST-DEMO-001", name="Demo Customer", contact="demo@example.invalid"))
        session.flush()
        def utc(day: int) -> datetime:
            return datetime(2026, 10, day, 8, tzinfo=timezone.utc)
        rows = [
            ("BF2026001", utc(2), None, "pending"),
            ("BF2026002", utc(3), utc(2), "shipped"),
            ("BF2026003", utc(2), utc(4), "shipped"),
        ]
        for order_id, promised, shipped, status in rows:
            if session.get(Order, order_id) is None:
                session.add(Order(order_id=order_id, customer_id="CUST-DEMO-001", created_at=utc(1), promised_ship_at=promised, shipped_at=shipped, status=status))


if __name__ == "__main__":
    initialize_demo_data(engine)
    print("Demo initialization complete; existing records preserved.")
