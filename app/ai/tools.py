# 模块职责：只读业务工具；区分未找到、查询失败和有效业务结果，不授予写入权限。

from sqlalchemy.exc import SQLAlchemyError
from app.ai.rag import retrieve_policy
from app.schemas.order import OrderResponse
from app.db.session import SessionLocal
from app.repositories.orders import get_order
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from app.services.access import can_read_customer
from app.services.shipping import assess_order_shipping
from app.core.time import BUSINESS_TIMEZONE

class OrderLookupInput(BaseModel):
    order_id: str = Field(
        description="需要查询的订单编号，例如 BF2026001",
        pattern=r"^BF\d{7}$",
    )


class CustomerLookupInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def lookup_customer(customer_id: str) -> dict[str, object]:
    """只读查询当前演示员工可见的客户资料，不允许任意客户范围。"""
    from app.repositories.customers import get_customer
    from app.schemas.customer import CustomerResponse
    try:
        with SessionLocal() as session:
            row = get_customer(session, customer_id)
            if row is None or not can_read_customer(customer_id):
                return {"status": "not_found", "data": None, "error": "客户不存在或无权访问"}
            return {"status": "success", "data": CustomerResponse.model_validate(row).model_dump(), "error": None}
    except SQLAlchemyError:
        return {"status": "failed", "data": None, "error": "客户查询暂不可用"}


customer_lookup_tool = StructuredTool.from_function(func=lookup_customer, args_schema=CustomerLookupInput)




def lookup_order(order_id: str) -> dict[str, object]:

    """
    函数用于查询订单,返回订单结果;只读查询，不创建或修改订单
    :param order_id: `BF` 加七位数字，例如 BF2026001
    :return: 订单结果字典,包含status,data,error；成功时额外包含assessment。
    :status: `success` 表示订单查询和发货评估成功，`not_found` 表示不存在，`failed` 表示查询或评估失败。
    :data: 成功时为订单字典，否则为 None
    :error: 失败或未找到时的提示，成功时为 None。
    :assessment: 包含order_id、服务端UTC查询时刻checked_at和确定性判断is_overdue_unshipped。
        该布尔值只表示是否超期未发货，不表示可以创建工单；失败时不可推断为不超期。
    """
    try:
        with SessionLocal() as session:
            order = get_order(session, order_id)
            if order is None or not can_read_customer(order.customer_id):
                return {
                    "status": "not_found",
                    "data": None,
                    "error": "订单不存在",
                }
            order_data = OrderResponse.model_validate(order).model_dump(mode="json")
            checked_at = datetime.now(timezone.utc).astimezone(BUSINESS_TIMEZONE)
            try:
                assessment = assess_order_shipping(order_data, checked_at)
            except ValueError:
                return {
                    "status": "failed",
                    "data": None,
                    "assessment": None,
                    "error": "订单数据不完整或存在冲突，暂时无法判断发货情况",
                }
            return {
                "status": "success",
                "data": order_data,
                "error": None,
                "assessment": assessment,
            }
    except SQLAlchemyError:
        return {
            "status": "failed",
            "data": None,
            "error": "订单查询暂时不可用，请稍后重试",
        }

order_lookup_tool = StructuredTool.from_function(
    func=lookup_order,
    args_schema=OrderLookupInput,

)


def search_policy(question: str) -> dict[str, object]:
    """根据用户问题,在知识库中检索相关政策,并返回政策内容"""



    try:
        documents = retrieve_policy(question,top_k=5)
        # 格式化政策内容
        sources = []
        for index, doc in enumerate(documents, start=1):
            sources.append({
                "text": doc.page_content,
                "chunk_id": doc.metadata["chunk_id"],
                "document_title": doc.metadata["document_title"],
                "section": doc.metadata["section"],
                "source": doc.metadata["source"],
                "score": doc.metadata["score"],
                **({"retrieval_method": "related_clause", "score_explanation": "关联补齐，score=0仅为兼容占位，不是向量相似度"}
                   if doc.metadata.get("retrieval_method") == "related_clause" else {}),
            })

        return {
            "status": "success" if sources else "not_found", # 无命中时为 "not_found"
            "data": sources, # 无命中时为 []
            "error": "未检索到相关政策，现有信息不足" if not sources else None,
        }
    except Exception:
        return {
            "status": "failed",
            "data": [],
            "error": "政策检索暂时不可用，请稍后重试",
        }


class PolicySearchInput(BaseModel):
    question: str = Field(
        description="需要检索的企业政策问题",
        min_length=1,
        max_length=2000,
    )

    @field_validator("question")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("用户问题不能为空")
        return value.strip()

policy_search_tool = StructuredTool.from_function(
    func=search_policy,
    args_schema=PolicySearchInput,
)
