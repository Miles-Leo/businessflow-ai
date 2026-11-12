# 模块职责：基础订单图节点；只返回增量状态，不直接修改传入 State。

import re
from app.ai.state import OrderQueryState
from app.ai.tools import lookup_order


def extract_order_id(state: OrderQueryState) -> dict[str, object]:
    # 读取输入，提取订单号，返回需要更新的字段
    order_id = re.search(r"BF\d{7}(?!\d)", state["user_input"])
    if order_id:
        return {
            "order_id": order_id.group(0),
            "execution_status": "running",
            "error": None
        }
    else:
        return{
            "order_id": None,  # 没提取到，用什么表示？
            "execution_status": "failed",  # 本次约定的失败状态
            "error": "未能提取到订单号",  # 提示用户提供有效订单号
        }


def query_order(state: OrderQueryState) -> dict[str, object]:
    # 根据 state 中的 order_id 查询订单
    order_id = state["order_id"]
    if order_id is None:
        return {
            "order": None,
            "execution_status": "failed",
            "error": "缺少订单号",
        }
    result = lookup_order(order_id)

    return {
        "order": result["data"],
        "execution_status": result["status"],
        "error": result["error"],
    }
