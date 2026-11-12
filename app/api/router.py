# 模块职责：聚合版本化 API 路由；各业务模块独立定义请求与响应契约。
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.repositories.orders import get_order
from app.schemas.order import OrderResponse
from app.api.agent import router as agent_router
from app.api.knowledge import router as knowledge_router
from app.api.approvals import router as approvals_router
from app.api.tickets import router as tickets_router
from app.api.feishu_sync import router as sync_router
from app.api.tasks import router as tasks_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.dependencies import DemoUser, get_demo_user
from app.services.access import can_read_customer
from app.repositories.customers import get_customer
from app.schemas.customer import CustomerResponse

router = APIRouter(prefix="/api/v1")
router.include_router(agent_router)
router.include_router(knowledge_router)
router.include_router(approvals_router)
router.include_router(tickets_router)
router.include_router(sync_router)
router.include_router(tasks_router)
router.include_router(auth_router)
router.include_router(documents_router)


@router.get("/orders/{order_id}", response_model=OrderResponse, tags=["orders"])
def query_order(order_id: str, session: Annotated[Session, Depends(get_db)],
                user: Annotated[DemoUser, Depends(get_demo_user)]) -> OrderResponse:
    order = get_order(session, order_id)
    if order is None or not can_read_customer(order.customer_id, user.role):
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse.model_validate(order)


@router.get("/customers/{customer_id}", response_model=CustomerResponse, tags=["customers"])
def query_customer(customer_id: str, session: Annotated[Session, Depends(get_db)],
                   user: Annotated[DemoUser, Depends(get_demo_user)]):
    customer = get_customer(session, customer_id)
    if customer is None or not can_read_customer(customer_id, user.role):
        raise HTTPException(404, "客户不存在或无权访问")
    return CustomerResponse.model_validate(customer)
