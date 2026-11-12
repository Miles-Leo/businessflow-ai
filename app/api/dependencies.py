# 模块职责：解析演示身份与角色权限；已有会话优先于客户端身份头。
"""Local demo identity selection only; not production authentication."""
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, Request


@dataclass(frozen=True)
class DemoUser:
    user_id: str
    role: Literal["employee", "manager"]


_DEMO_USERS = {
    "employee-demo-001": DemoUser("employee-demo-001", "employee"),
    "reviewer-demo-001": DemoUser("reviewer-demo-001", "manager"),
}


def get_demo_user(
    request: Request,
    user_id: Annotated[str | None, Header(alias="X-Demo-User", description="本地演示身份选择，不是真实认证")] = None,
) -> DemoUser:
    # A signed browser session takes precedence; a forged header cannot change its role.
    user_id = request.scope.get("session", {}).get("demo_user_id") or user_id
    user = _DEMO_USERS.get(user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "请提供有效的演示用户")
    return user


def require_reviewer(user: Annotated[DemoUser, Depends(get_demo_user)]) -> DemoUser:
    if user.role != "manager":
        raise HTTPException(403, "仅负责人可以审核")
    return user
