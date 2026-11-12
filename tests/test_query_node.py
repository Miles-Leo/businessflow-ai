from unittest.mock import patch
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from app.ai.nodes import query_order


@pytest.mark.parametrize("failure_stage", ["connect", "query"])
def test_database_failure_returns_safe_error(failure_stage):
    state = {
        "user_input": "查询订单 BF2026001",
        "order_id": "BF2026001",
        "order": None,
        "execution_status": "running",
        "error": None,
    }
    original = state.copy()
    failure = OperationalError("SELECT private_data", {}, RuntimeError("internal-secret"))
    with patch("app.ai.tools.SessionLocal") as session_factory, patch(
        "app.ai.tools.get_order"
    ) as repository:
        if failure_stage == "connect":
            session_factory.return_value.__enter__.side_effect = failure
        else:
            repository.side_effect = failure

        result = query_order(state)

    assert result == {
        "order": None,
        "execution_status": "failed",
        "error": "订单查询暂时不可用，请稍后重试",
    }
    assert "internal-secret" not in result["error"]
    assert "SELECT" not in result["error"]
    assert state == original
    if failure_stage == "query":
        session_factory.return_value.__exit__.assert_called_once()

def test_query_order_branches(db_engine):
    state = {"user_input": "查询订单", "order_id": None, "order": None, "execution_status": "pending", "error": None}
    original = state.copy()
    with patch("app.ai.tools.SessionLocal", side_effect=AssertionError("Should not access database")):
        assert query_order(state) == {"order": None, "execution_status": "failed", "error": "缺少订单号"}
    assert state == original
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)):
        missing = dict(state, order_id="BF9999999")
        assert query_order(missing) == {"order": None, "execution_status": "not_found", "error": "订单不存在"}
        found = dict(state, order_id="BF2026001")
        result = query_order(found)
        assert result["execution_status"] == "success"
        assert result["error"] is None
        assert result["order"]["order_id"] == "BF2026001"
        assert result["order"]["created_at"].endswith("+08:00")
        assert found["order"] is None
        assert found["execution_status"] == "pending"
