from app.ai.nodes import extract_order_id
from app.ai.state import OrderQueryState


def test_extract_order_id_success():
    state: OrderQueryState = {
        "user_input": "查询订单状态",
        "order_id": None,
        "order": None,
        "execution_status": "pending",
        "error": None,
    }

    result = extract_order_id(state)

    # TODO：检查 result 中的订单号、状态和 error
    assert result["order_id"] is None
    assert result["execution_status"] == "failed"
    assert result["error"]


    # TODO：检查原 state 的 order_id 仍为 None
    assert state["order_id"] is None
    assert state["execution_status"] == "pending"
