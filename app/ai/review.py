# 模块职责：构造订单事实与待审核建议，并在独立审核图中暂停等待人工决定。

from app.ai.state import TicketProposal
from langgraph.types import interrupt
from app.ai.state import TicketReviewState
from datetime import datetime, timezone
from app.ai.tools import lookup_order, search_policy
from app.services.trace import record_step
from app.core.time import business_display


def build_ticket_proposal(
    order_result: dict[str, object],
    policy_result: dict[str, object],
) -> TicketProposal:

    if order_result["status"] != "success":
        raise ValueError("订单查询失败, 无法生成工单建议")


    assessment = order_result["assessment"]
    if assessment["is_overdue_unshipped"] is not True:
        raise ValueError("订单不属于超期未发货，不能生成此类工单建议")


    if policy_result["status"] != "success":
        raise ValueError("政策查询失败, 无法生成工单建议")


    if not policy_result["data"]:
        raise ValueError("政策查询结果为空, 无法生成工单建议")

    # 仅检查固定演示政策的条款覆盖，不代表真实性或适用性验证。
    section_codes = set()
    for passage in policy_result["data"]:
        section = passage["section"]
        section_codes.add(section.split("：", 1)[0])

    if not {"AS-04", "AS-05"}.issubset(section_codes):
        raise ValueError("缺少处理建议或审核边界条款，暂不能生成建议")

    policy_sources = []
    for passage in policy_result["data"]:
        section_code = passage["section"].split("：", 1)[0]
        if section_code in {"AS-04", "AS-05"}:
            policy_sources.append({
                "document_title": passage["document_title"],
                "section": passage["section"],
                "source": passage["source"],
                "chunk_id": passage["chunk_id"],
            })


    order = order_result["data"]
    description = (
        f"订单 {order['order_id']}，"
        f"承诺发货时间为 {business_display(order['promised_ship_at'])}，"
        f"截至 {business_display(assessment['checked_at'])} 尚未发货，已超过承诺时间，"
        "建议核查发货进展及延迟原因。"
    )
    return {
        "order_id": order["order_id"],
        "issue_type": "shipping_delay",
        "description": description,  # 描述订单事实及核查建议
        "policy_sources": policy_sources,
        "checked_at": assessment["checked_at"],  # 从 assessment 取查询时刻
        "approval_status": "pending",
    }


# 中断工作流进入审核阶段
# 维护约束：interrupt 恢复后节点可能重新执行；中断前不放置不可重复的业务副作用。
def wait_for_review(state: TicketReviewState) -> dict[str, object]:
    if state["proposal"]["approval_status"] != "pending":
        raise ValueError("该建议已经完成审核， 无法重复审核")

    decision = interrupt(
        {
            "message": "请审核工单创建建议",
            "proposal": state["proposal"],
        }
    )

    if not isinstance(decision, dict):
        raise ValueError("审核结果必须是字典类型")

    action = decision.get("decision")
    if action not in ("approved", "rejected"):
        raise ValueError("审核结果必须是 approved 或 rejected")

    reviewer_id = decision.get("reviewer_id")

    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        raise ValueError("审核人不能为空")

    proposal = state["proposal"].copy()
    proposal["approval_status"] = action
    reviewed_at = datetime.now(timezone.utc).isoformat()

    return {"proposal": proposal, "reviewer_id": reviewer_id.strip(), "reviewed_at": reviewed_at}


def prepare_ticket_proposal(order_id: str) -> TicketProposal:



    order = lookup_order(order_id)
    record_step("lookup_order", order.get("status") != "success", tool=True)

    policy_result = search_policy("超期未发货时提出发货延迟核查建议的条件，以及负责人审核和正式创建工单的限制是什么？")
    record_step("search_policy", policy_result.get("status") != "success", tool=True)


    proposal = build_ticket_proposal(order, policy_result)

    return proposal


# 维护约束：保留查询时刻的事实快照；审核后的当前事实需要在正式执行时另行校验。
def prepare_ticket_proposal_result(order_id: str, *, structured: bool = False) -> tuple[TicketProposal | None, str] | tuple[TicketProposal | None, str, dict]:
    """Query once; keep the facts used for the conditional proposal."""
    order_result = lookup_order(order_id)
    record_step("lookup_order", order_result.get("status") != "success", tool=True)
    if order_result.get("status") != "success" or not order_result.get("assessment"):
        raise ValueError("订单查询或评估未成功")
    order, assessment = order_result["data"], order_result["assessment"]
    result = {"query_result": order, "assessment": assessment, "policy_sources": [], "proposal": None, "execution_result": None}
    lines = ["订单查询结果", f"订单编号：{order['order_id']}",
             f"订单状态：{order['status']}", f"创建时间：{business_display(order['created_at'])}",
             f"承诺发货时间：{business_display(order['promised_ship_at'])}",
             f"实际发货时间：{business_display(order['shipped_at']) if order['shipped_at'] else '尚未发货'}",
             f"查询时刻：{business_display(assessment['checked_at'])}",
             f"超期未发货判定：{'是' if assessment['is_overdue_unshipped'] else '否'}"]
    if not assessment["is_overdue_unshipped"]:
        lines.append("不符合超期未发货条件，本次未生成待审核建议，也未创建正式工单。")
        return (None, "\n".join(lines), result) if structured else (None, "\n".join(lines))
    policy_result = search_policy("超期未发货时提出发货延迟核查建议的条件，以及负责人审核和正式创建工单的限制是什么？")
    record_step("search_policy", policy_result.get("status") != "success", tool=True)
    try:
        proposal = build_ticket_proposal(order_result, policy_result)
    except ValueError:
        if not structured:
            raise
        if policy_result.get("status") == "failed":
            result["issue"] = "政策检索服务暂不可用，请检查 Milvus/Docker 与 Embedding 服务后重新提交；订单查询结果已保留，未生成审核建议。"
        elif policy_result.get("status") == "not_found" or not policy_result.get("data"):
            result["issue"] = "未检索到适用政策，订单查询结果已保留，未生成审核建议。"
        else:
            result["issue"] = "政策条款不足，缺少处理建议或审核边界依据；订单查询结果已保留，未生成审核建议。"
        return None, "\n".join(lines), result
    lines += ["", "待审核建议：发起发货延迟核查，核查发货进展及延迟原因。", "政策依据："]
    for source in proposal["policy_sources"]:
        lines.append(f"《{source['document_title']}》｜{source['section']}｜{source['source']}")
    result.update(policy_sources=proposal["policy_sources"], proposal=proposal)
    return (proposal, "\n".join(lines), result) if structured else (proposal, "\n".join(lines))
