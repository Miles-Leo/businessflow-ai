# 模块职责：确定性发货评估；校验带时区时间和数据冲突，不依赖模型猜测。
from datetime import datetime


def is_overdue_unshipped(
    promised_ship_at: datetime,
    shipped_at: datetime | None,
    checked_at: datetime,
) -> bool:
    #判断三个参数是否有时区信息
    for value in (promised_ship_at, checked_at, shipped_at):
        if value is None:
            continue

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{value} 必须有时区信息")


    if shipped_at is None and checked_at > promised_ship_at:
        return True

    return False



# 维护约束：False 仅表示不属于超期未发货，不能直接解释为按时发货。
def assess_order_shipping(
    order: dict[str, object],
    checked_at: datetime,
) -> dict[str, object]:
    required_fields = (
        "order_id",
        "promised_ship_at",
        "shipped_at",
        "status",
    )
    for field in required_fields:
        if field not in order:
            raise ValueError(f"订单数据缺少 {field} 字段")

    if isinstance(order["promised_ship_at"], str):
        try:
            promised = datetime.fromisoformat(order["promised_ship_at"])
        except ValueError:
            raise ValueError("promised_ship_at 必须是有效的 ISO 8601 时间字符串")
    else:
        raise ValueError("promised_ship_at 必须为字符串")

    if order["shipped_at"] is None:
        shipped = None
    elif isinstance(order["shipped_at"], str):
        try:
            shipped = datetime.fromisoformat(order["shipped_at"])
        except ValueError:
            raise ValueError("shipped_at 必须是有效的 ISO 8601 时间字符串")
    else:
        raise ValueError("shipped_at 必须为字符串或 None")


    overdue = is_overdue_unshipped(promised, shipped, checked_at)

    if order["status"] == "shipped" and shipped is None:
        raise ValueError("已发货订单必须有发货时间")

    if shipped is not None:
        if shipped > checked_at:
            raise ValueError("实际发货时间晚于查询时刻，数据需要核对")


    return{
        "order_id": order["order_id"],  # 从 order 读取
        "checked_at": checked_at.isoformat(),  # 用 checked_at.isoformat()
        "is_overdue_unshipped": overdue,  # 已有函数的判断结果
    }
