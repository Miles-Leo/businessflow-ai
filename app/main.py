# 模块职责：FastAPI 组合入口；注册中间件、路由及静态页面，不自动建表或写入演示数据。
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from app.api.router import router
from app.core.config import get_settings
from app.frontend import configure_frontend
from starlette.middleware.sessions import SessionMiddleware
from secrets import token_urlsafe

#实例化FastAPI应用
app = FastAPI(title=get_settings().app_name)
app.add_middleware(SessionMiddleware,
    secret_key=get_settings().demo_session_secret.get_secret_value() or token_urlsafe(32),
    session_cookie="businessflow_session", max_age=8 * 60 * 60,
    same_site="lax", https_only=get_settings().demo_session_https_only,
)
app.include_router(router)
configure_frontend(app)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError):
    return JSONResponse(status_code=503, content={"detail": "业务数据库暂不可用，请检查初始化与服务状态"})

@app.get("/health")
def health_check():

    return {
        "status": "ok",
        "service": "businessflow-ai"
    }
