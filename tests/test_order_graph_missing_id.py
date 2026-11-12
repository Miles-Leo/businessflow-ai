from app.ai.graph import condition_graph
from app.ai.state import OrderQueryState
from unittest.mock import patch



def test_missing_order_id_does_not_access_database():
    initial_state: OrderQueryState = {
        "user_input": "帮我查询订单",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    with patch("app.ai.tools.SessionLocal") as mock_session:
        result = condition_graph.invoke(initial_state)

    # 没有订单号时，不应创建数据库会话。
    mock_session.assert_not_called()

    assert result["execution_status"] == "failed"
    assert result["order_id"] is None
    assert result["order"] is None
    assert result["error"]
