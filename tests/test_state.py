from app.ai.state import OrderQueryState


def test_initial_state():
    initial_state: OrderQueryState = {
        "user_input": "查询订单 BF2026001 的当前状态。",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    assert initial_state["order_id"] is None
    # 再检查 order 为 None、execution_status 为 "pending"
    assert initial_state["order"] is None
    assert initial_state["execution_status"] is "pending"
