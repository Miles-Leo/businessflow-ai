# 模块职责：本地演示登录与签名会话；不是企业账号密码认证。
"""Local demo account sessions, deliberately not enterprise password authentication."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/auth", tags=["demo-auth"])
ACCOUNTS = {
    "employee-demo-001": {"user_id": "employee-demo-001", "role": "employee", "display_name": "演示员工"},
    "reviewer-demo-001": {"user_id": "reviewer-demo-001", "role": "manager", "display_name": "演示负责人"},
}


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: Literal["employee-demo-001", "reviewer-demo-001"]


@router.post("/login")
def demo_login(request: Request, body: DemoLoginRequest):
    request.session.clear()
    request.session["demo_user_id"] = body.user_id
    return ACCOUNTS[body.user_id]


@router.get("/me")
def current_session(request: Request):
    user_id = request.session.get("demo_user_id")
    if user_id not in ACCOUNTS:
        raise HTTPException(401, "请先登录演示账户")
    return ACCOUNTS[user_id]


@router.post("/logout")
def demo_logout(request: Request):
    request.session.clear()
    return {"message": "已退出登录"}
