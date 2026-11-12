from unittest.mock import patch
from sqlalchemy.orm import sessionmaker

from app.ai.graph import condition_graph
from app.ai.state import OrderQueryState


def test_order_graph_success(db_engine):
    initial_state: OrderQueryState = {
        "user_input": "查询订单 BF2026001",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    with patch(
        "app.ai.tools.SessionLocal",
        sessionmaker(bind=db_engine),
    ):
        result = condition_graph.invoke(initial_state)

    # TODO：检查 result["execution_status"] 是否为 "success"
    assert result["execution_status"] == "success"
    # TODO：检查 result["order"]["order_id"] 是否为 "BF2026001"
    assert result["order"]["order_id"] == "BF2026001"


def test_order_graph_not_found(db_engine):
    initial_state: OrderQueryState = {
        "user_input": "查询订单 BF9999999",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    with patch(
        "app.ai.tools.SessionLocal",
        sessionmaker(bind=db_engine),
    ):
        result = condition_graph.invoke(initial_state)

    # TODO：检查 result["execution_status"] 是否为 "not_found"
    assert result["execution_status"] == "not_found"
    # TODO：检查 result["order"] 是否为 None
    assert result["order"] is None


def test_order_graph_missing_id(db_engine):
    initial_state: OrderQueryState = {
        "user_input": "查询订单",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    with patch(
        "app.ai.tools.SessionLocal",
        sessionmaker(bind=db_engine),
    ):
        result = condition_graph.invoke(initial_state)

    # TODO：检查 result["execution_status"] 是否为 "failed"
    assert result["execution_status"] == "failed"
    # TODO：检查 result["order_id"] 是否为 None
    assert result["order_id"] is None
    assert result["error"]
